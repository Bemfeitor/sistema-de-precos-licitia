from sqlalchemy import inspect, text


OFFER_COLUMN_UPDATES = [
    "ADD COLUMN IF NOT EXISTS validated_price DOUBLE PRECISION",
    "ADD COLUMN IF NOT EXISTS price_match BOOLEAN NOT NULL DEFAULT FALSE",
    "ADD COLUMN IF NOT EXISTS validation_method VARCHAR",
    "ADD COLUMN IF NOT EXISTS is_best_seller BOOLEAN NOT NULL DEFAULT FALSE",
    "ADD COLUMN IF NOT EXISTS sold_quantity INTEGER",
    "ADD COLUMN IF NOT EXISTS validation_checked_at TIMESTAMP",
]


def ensure_offer_columns(engine) -> None:
    inspector = inspect(engine)
    if "offers" not in inspector.get_table_names():
        return

    with engine.begin() as connection:
        for clause in OFFER_COLUMN_UPDATES:
            connection.execute(text(f"ALTER TABLE offers {clause}"))
