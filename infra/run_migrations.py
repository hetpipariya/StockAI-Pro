import re
import sqlalchemy as sa
from sqlalchemy import text

# Database DSNs
quant_dsn = "postgresql://postgres:Pipariya123@localhost:5432/quant_engine"
trading_dsn = "postgresql://postgres:Pipariya123@localhost:5432/trading_db"

def get_table_name_from_query(query: str) -> str:
    """Extracts table name from standard SQL CREATE INDEX / DROP INDEX / ALTER TABLE queries."""
    q_upper = query.upper()
    
    # 1. Matches "ON <table>" (e.g. CREATE INDEX ix_orders ON orders ...)
    on_match = re.search(r'\bON\b\s+([a-zA-Z_0-9"]+)', query, re.IGNORECASE)
    if on_match:
        return on_match.group(1).replace('"', '').strip()
        
    # 2. Matches "ALTER TABLE <table>"
    alter_match = re.search(r'\bALTER\s+TABLE\s+([a-zA-Z_0-9"]+)', query, re.IGNORECASE)
    if alter_match:
        return alter_match.group(1).replace('"', '').strip()
        
    return ""

def run_index_migrations(dsn: str, db_name: str):
    print(f"\n>>> Running Index Migrations on {db_name}...")
    engine = sa.create_engine(dsn)
    
    with open("infra/migrations/migration_001_indexes.sql", "r", encoding="utf-8") as f:
        content = f.read()
        
    # Split by semicolon
    statements = content.split(";")
    
    with engine.begin() as conn:
        # Get list of existing tables in this database
        existing_tables_res = conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
        )).fetchall()
        existing_tables = {row[0].lower() for row in existing_tables_res}
        
        for statement in statements:
            stmt_clean = statement.strip()
            if not stmt_clean or stmt_clean.startswith("--"):
                continue
                
            # Check target table
            target_table = get_table_name_from_query(stmt_clean)
            if target_table:
                if target_table.lower() not in existing_tables:
                    # Skip statement since target table doesn't exist in this database
                    # print(f"Skipping index operation (table '{target_table}' not in {db_name})")
                    continue
            
            # Execute statement
            print(f"Executing: {stmt_clean[:80].replace(chr(10), ' ')}...")
            try:
                conn.execute(text(stmt_clean))
            except Exception as e:
                print(f"Error executing query: {e}")

def run_timescale_migrations(dsn: str, db_name: str):
    print(f"\n>>> Running Timescale Migrations on {db_name}...")
    engine = sa.create_engine(dsn)
    
    with open("infra/migrations/migration_002_timescale.sql", "r", encoding="utf-8") as f:
        content = f.read()
        
    stmt_clean = content.strip()
    if not stmt_clean:
        return
        
    with engine.begin() as conn:
        print("Executing entire TimescaleDB PL/pgSQL DO block...")
        try:
            conn.execute(text(stmt_clean))
            print("TimescaleDB PL/pgSQL DO block executed successfully.")
        except Exception as e:
            print(f"Error executing TimescaleDB DO block: {e}")

if __name__ == "__main__":
    print("==========================================")
    # 1. Run index migrations
    run_index_migrations(quant_dsn, "quant_engine")
    run_index_migrations(trading_dsn, "trading_db")
    
    # 2. Run timescale migrations
    run_timescale_migrations(quant_dsn, "quant_engine")
    run_timescale_migrations(trading_dsn, "trading_db")
    print("==========================================")
    print("MIGRATION COMPLETE!")
