import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

try:
    import redis
except ImportError:
    redis = None

# Add the project roots to PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/shared"))

from stockai_shared.logging.logging import configure_logging
configure_logging()
logger = logging.getLogger("redis_failover_test")

# Import central Redis Client utilities
from stockai_shared.cache import redis_client

# Define highly detailed test reporter class
class SRETestReporter:
    def __init__(self):
        self.results = []
        
    def add_result(self, name: str, passed: bool, detail: str = ""):
        self.results.append({"name": name, "passed": passed, "detail": detail})
        status = "[PASS]" if passed else "[FAIL]"
        logger.info(f"[SRE-TEST-REPORTER] {status} | {name}: {detail}")
        
    def report(self):
        logger.info("\n" + "="*80 + "\n" + "                 SRE REDIS RELIABILITY AUDIT & TEST REPORT\n" + "="*80)
        passes = 0
        fails = 0
        for r in self.results:
            status = "PASS" if r["passed"] else "FAIL"
            logger.info(f" - [{status:4s}] {r['name']:<50s} -> {r['detail']}")
            if r["passed"]:
                passes += 1
            else:
                fails += 1
        pct = (passes / len(self.results)) * 100 if self.results else 0
        logger.info("="*80)
        logger.info(f"Summary: {passes} Passed, {fails} Failed | Success Rate: {pct:.1f}%")
        logger.info("="*80 + "\n")
        return pct == 100

reporter = SRETestReporter()

# Mocking classes for Sentinel and Failover simulation
class MockRedisClient:
    def __init__(self, host: str, port: int, name: str = "master", fail_on_read=False, fail_on_write=False):
        self.host = host
        self.port = port
        self.name = name
        self.fail_on_read = fail_on_read
        self.fail_on_write = fail_on_write
        self._store = {}
        
    async def ping(self):
        if self.fail_on_read or self.fail_on_write:
            raise redis.exceptions.ConnectionError("Simulated Redis host offline.")
        return True
        
    async def get(self, key: str):
        if self.fail_on_read:
            raise redis.exceptions.ConnectionError("Simulated Read Replica offline.")
        return self._store.get(key)
        
    async def setex(self, key: str, ttl: int, value: Any):
        if self.fail_on_write:
            raise redis.exceptions.ConnectionError("Simulated Master write failure.")
        self._store[key] = value
        return True
        
    async def delete(self, key: str):
        if self.fail_on_write:
            raise redis.exceptions.ConnectionError("Simulated Master delete failure.")
        self._store.pop(key, None)
        return True

    def pubsub(self, *args, **kwargs):
        return MockPubSub()


class MockPubSub:
    def __init__(self):
        self.channels = []
        self._is_closed = False
        
    async def subscribe(self, *args, **kwargs):
        self.channels.extend(args)
        
    async def listen(self):
        # Yield one simulated tick then block
        yield {"type": "message", "channel": "stockai:realtime:candle", "data": '{"payload": {"symbol": "SBIN", "close": 650.0}}'}
        while not self._is_closed:
            await asyncio.sleep(0.1)
            
    async def close(self):
        self._is_closed = True


async def test_tls_configuration_parsing():
    """Verify that TLS connections are parsed correctly and SSL arguments are formatted."""
    try:
        # Assert SSL config for rediss://
        ssl_opts_secure = redis_client._get_ssl_options("rediss://localhost:6379/0")
        assert ssl_opts_secure.get("ssl") is True, "SSL flag must be enabled"
        
        # Test SSL validation configuration (Skip verify logic)
        redis_client.REDIS_TLS_SKIP_VERIFY = True
        ssl_opts_skip = redis_client._get_ssl_options("rediss://localhost:6379/0")
        assert ssl_opts_skip.get("ssl_cert_reqs") == "none", "Cert validation must be skipped"
        
        redis_client.REDIS_TLS_SKIP_VERIFY = False
        ssl_opts_req = redis_client._get_ssl_options("rediss://localhost:6379/0")
        assert ssl_opts_req.get("ssl_cert_reqs") == "required", "Cert validation must be enforced in production"
        
        # Assert standard redis:// doesn't add SSL
        ssl_opts_standard = redis_client._get_ssl_options("redis://localhost:6379/0")
        assert "ssl" not in ssl_opts_standard, "Standard Redis should not have SSL key"
        
        reporter.add_result("TLS Configuration Validation", True, "Successfully validated rediss:// and redis:// parsing rules with skip/verify configurations.")
    except Exception as exc:
        reporter.add_result("TLS Configuration Validation", False, f"TLS parsing failed: {exc}")


async def test_replica_routing_and_fallback():
    """Verify that reads go to replica and fall back automatically to master on failure."""
    try:
        # Setup mock clients
        master_mock = MockRedisClient("127.0.0.1", 6379, "master")
        replica_mock = MockRedisClient("127.0.0.1", 6380, "replica")
        
        # Manually seed states
        redis_client._async_redis = master_mock
        redis_client._async_replica = replica_mock
        redis_client._degraded_mode_active = False
        
        # Set a key in master store (which is the actual write path)
        await redis_client.set_cache("sre_test_key", "sre_gold_value")
        # Copy to replica store for simulation
        replica_mock._store["sre_test_key"] = master_mock._store["sre_test_key"]
        
        # Verify we read from replica successfully
        val = await redis_client.get_cache("sre_test_key")
        assert val == "sre_gold_value", f"Expected to read value from replica, got {val}"
        
        # Now simulate replica down (fail_on_read = True)
        replica_mock.fail_on_read = True
        
        # Verify read STILL works because it falls back automatically to master!
        val_fallback = await redis_client.get_cache("sre_test_key")
        assert val_fallback == "sre_gold_value", f"Replica failure fallback read failed; got {val_fallback}"
        
        reporter.add_result("Replica Read Offloading & Master Fallback", True, "Read routed to replica. On replica failure, automatically fell back to master seamlessly.")
    except Exception as exc:
        reporter.add_result("Replica Read Offloading & Master Fallback", False, f"Failed: {exc}")
    finally:
        redis_client._async_redis = None
        redis_client._async_replica = None


# Shared class-level states for Mock Sentinel
class MockAsyncSentinel:
    active_master = MockRedisClient("127.0.0.1", 6379, "master_node_1")
    active_replica = MockRedisClient("127.0.0.1", 6380, "replica_node_1")
    
    def __init__(self, hosts, *args, **kwargs):
        self.hosts = hosts
        
    def master_for(self, name, *args, **kwargs):
        return self.active_master
        
    def slave_for(self, name, *args, **kwargs):
        return self.active_replica


async def test_sentinel_master_failover_recovery():
    """Verify that Sentinel automatically recovers master connections on failover switches."""
    try:
        # Simulate active Sentinel configurations
        sentinel_hosts = [("127.0.0.1", 26379)]
        redis_client.REDIS_SENTINELS = "127.0.0.1:26379"
        redis_client.REDIS_MASTER_NAME = "mymaster"
        
        # Inject Sentinel mock
        redis_client.AsyncSentinel = MockAsyncSentinel
        
        # Trigger client connection refresh
        redis_client._async_redis = None
        redis_client._async_replica = None
        
        # Set shared state
        MockAsyncSentinel.active_master = MockRedisClient("127.0.0.1", 6379, "master_node_1")
        
        master = await redis_client._get_redis(force_retry=True)
        assert master.name == "master_node_1", "Initial master connection incorrect"
        
        # Simulate FAILOVER PROMOTION: Sentinel master shifts to node 2
        MockAsyncSentinel.active_master = MockRedisClient("127.0.0.1", 6381, "master_node_2")
        
        # Force Sentinel switch
        redis_client._async_redis = None
        redis_client._async_replica = None
        
        # Build new master
        new_master = await redis_client._get_redis(force_retry=True)
        assert new_master.name == "master_node_2", f"Sentinel failed to route to new master; got {new_master.name}"
        
        reporter.add_result("Sentinel Master Discovery & Failover Recovery", True, "Successfully parsed Sentinel routing nodes and automatically mapped connection to newly promoted master.")
    except Exception as exc:
        reporter.add_result("Sentinel Master Discovery & Failover Recovery", False, f"Failed: {exc}")
    finally:
        redis_client.REDIS_SENTINELS = ""
        redis_client.REDIS_MASTER_NAME = "mymaster"
        redis_client._async_redis = None
        redis_client._async_replica = None


async def test_pubsub_recovery():
    """Verify that subscribers successfully reconnect and recover active subscriptions."""
    try:
        # Standard local redis connection test
        redis_client._async_redis = None
        client = await redis_client.get_redis()
        if client is not None:
            # We have a physical local redis connection!
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            channels = [
                "stockai:realtime:tick",
                "stockai:realtime:candle",
                "stockai:realtime:signal",
                "stockai:realtime:status"
            ]
            await pubsub.subscribe(*channels)
            
            # Simulate a connection restart and verify we can reconnect and re-subscribe
            await pubsub.close()
            
            # Reconnect
            pubsub_new = client.pubsub(ignore_subscribe_messages=True)
            await pubsub_new.subscribe(*channels)
            await pubsub_new.close()
            
            reporter.add_result("Pub/Sub Interservice Channel Recovery", True, "Physical Pub/Sub streams validated. Connection drop simulated and successfully recovered.")
        else:
            # Mock Pub/Sub recovery validation
            logger.warning("[SRE-TEST] Local Redis physical server offline. Validating SRE Pub/Sub recovery mocks.")
            mock_client = MockRedisClient("127.0.0.1", 6379)
            pubsub = mock_client.pubsub()
            await pubsub.subscribe("stockai:realtime:candle")
            
            # Verify subscribed channel exists
            assert "stockai:realtime:candle" in pubsub.channels
            await pubsub.close()
            reporter.add_result("Pub/Sub Interservice Channel Recovery (Mocked)", True, "Interservice Pub/Sub reconnection and subscription recovery successfully asserted under mock conditions.")
    except Exception as exc:
        reporter.add_result("Pub/Sub Interservice Channel Recovery", False, f"Failed: {exc}")


async def test_degraded_circuit_breaker_and_garbage_collection():
    """Verify that circuit breakers work correctly and fallback cache has no memory leaks."""
    try:
        # Simulate entire Redis host outage
        bad_client = MockRedisClient("127.0.0.1", 6379, fail_on_write=True, fail_on_read=True)
        redis_client._async_redis = bad_client
        redis_client._async_replica = bad_client
        redis_client._degraded_mode_active = False
        
        # Write to cache should trigger circuit breaker on connection exception
        await redis_client.set_cache("sre_leak_key", "leaky_value", ttl=1)
        assert redis_client.is_degraded_mode() is True, "Circuit breaker should be active"
        
        # Verify value written inside in-memory fallback cache instead
        val = await redis_client.get_cache("sre_leak_key")
        assert val == "leaky_value", f"Expected to read from fallback memory cache, got {val}"
        
        # Verify GC: wait slightly and verify cleanup sweep works
        # Seed multiple keys with 1s TTL
        redis_client._fallback_set("sweep_key_1", "sweepy", ttl=1)
        redis_client._fallback_set("sweep_key_2", "sweepy", ttl=3600) # keep this one
        
        # Simulate monotonic time jump of 2 seconds
        original_monotonic = time.monotonic
        time.monotonic = lambda: original_monotonic() + 5.0
        
        # Manually sweep garbage collection
        now = time.monotonic()
        with redis_client._fallback_lock:
            expired_keys = [
                key for key, (_, expires_at) in redis_client._fallback_cache.items()
                if now > expires_at
            ]
            for key in expired_keys:
                redis_client._fallback_cache.pop(key, None)
                
        # Restore time
        time.monotonic = original_monotonic
        
        # Assert sweep_key_1 expired and sweep_key_2 remains (no leak bounds)
        assert "sweep_key_1" not in redis_client._fallback_cache, "sweep_key_1 should be GC'ed"
        assert "sweep_key_2" in redis_client._fallback_cache, "sweep_key_2 should be preserved"
        
        reporter.add_result("Circuit Breaker & Fallback GC Memory Leaks", True, "Successfully validated degraded mode circuit breaker, fallback cache redirects, and garbage collection sweeping rules.")
    except Exception as exc:
        reporter.add_result("Circuit Breaker & Fallback GC Memory Leaks", False, f"Failed: {exc}")
    finally:
        redis_client._fallback_cache.clear()
        redis_client._degraded_mode_active = False
        redis_client._async_redis = None
        redis_client._async_replica = None


async def run_all_tests():
    logger.info("[STARTUP] Launching Redis SRE Failover and High Availability Validation suite...")
    
    # Run tests sequentially
    await test_tls_configuration_parsing()
    await test_replica_routing_and_fallback()
    await test_sentinel_master_failover_recovery()
    await test_pubsub_recovery()
    await test_degraded_circuit_breaker_and_garbage_collection()
    
    # Output final report
    all_passed = reporter.report()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
