from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
ENTRY_DIR = ROOT / "backend" / "models" / "entry_5m"
TREND_DIR = ROOT / "backend" / "models" / "trend_1h"
OUT_DIR = ROOT / "backend" / "models" / "reports"
OUT_PATH = OUT_DIR / "final_production_readiness_report.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_model_section(model_dir: Path) -> dict[str, Any]:
    validation = _read_json(model_dir / "validation_report.json")
    metrics = _read_json(model_dir / "training_metrics.json")
    metadata = _read_json(model_dir / "metadata.json")
    importance = _read_json(model_dir / "feature_importance.json")
    shap = _read_json(model_dir / "shap_report.json")
    correlation = _read_json(model_dir / "feature_correlation_heatmap.json")
    production = _read_json(model_dir / "production_validation.json")
    risk = _read_json(model_dir / "risk_signal_validation.json")

    return {
        "model_dir": str(model_dir),
        "feature_computation_latency": production.get("prediction_latency", {}),
        "model_metrics": validation,
        "feature_importance": importance,
        "shap_analysis": shap,
        "correlation_heatmap": correlation,
        "realtime_inference_benchmarks": {
            "concurrency": production.get("concurrent_benchmark", {}),
            "multi_user": production.get("multi_user_inference", {}),
        },
        "websocket_stability": production.get("websocket_inference_stability", False),
        "redis_compatibility": production.get("redis_compatibility", False),
        "bundle_endpoint_compatibility": production.get("bundle_endpoint_compatibility", False),
        "risk_signal_validation": risk,
        "training_summary": metrics,
        "metadata": metadata,
    }


def build_final_report() -> dict[str, Any]:
    entry = _extract_model_section(ENTRY_DIR)
    trend = _extract_model_section(TREND_DIR)

    bottlenecks: list[str] = []
    for section_name, section in (("entry_5m", entry), ("trend_1h", trend)):
        latency = float(section.get("feature_computation_latency", {}).get("latency_ms", -1.0))
        if latency < 0 or latency > 2.0:
            bottlenecks.append(f"{section_name}: latency target <2ms not met")

        concurrency = section.get("realtime_inference_benchmarks", {}).get("concurrency", {})
        p95 = float(concurrency.get("p95_latency_ms", -1.0)) if isinstance(concurrency, dict) else -1.0
        if p95 < 0:
            bottlenecks.append(f"{section_name}: missing concurrency p95 latency")

        websocket_ok = bool(section.get("websocket_stability", False))
        if not websocket_ok:
            bottlenecks.append(f"{section_name}: websocket stability check failed")

    production_ready = len(bottlenecks) == 0

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "feature_schema": "strict_20_feature_cpp_native",
        "entry_5m": entry,
        "trend_1h": trend,
        "memory_usage": {
            "note": "Memory usage is environment-dependent; run service profiler in deployment pod for exact figures."
        },
        "concurrency_stability": {
            "entry_5m": entry.get("realtime_inference_benchmarks", {}).get("concurrency", {}),
            "trend_1h": trend.get("realtime_inference_benchmarks", {}).get("concurrency", {}),
        },
        "remaining_bottlenecks": bottlenecks,
        "production_readiness_status": "READY" if production_ready else "NEEDS_ATTENTION",
    }
    return report


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = build_final_report()
    OUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
