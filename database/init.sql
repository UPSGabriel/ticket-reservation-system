CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0)
);

CREATE TABLE IF NOT EXISTS inventory (
    event_id INTEGER PRIMARY KEY,
    available INTEGER NOT NULL CHECK (available >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_inventory_event
        FOREIGN KEY (event_id)
        REFERENCES events(id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reservations (
    id UUID PRIMARY KEY,
    event_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status VARCHAR(50) NOT NULL,
    payment_status VARCHAR(50) NOT NULL,
    notification_status VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_reservation_event
        FOREIGN KEY (event_id)
        REFERENCES events(id)
);

INSERT INTO events (id, name, price)
VALUES
    (1, 'Concierto UPS', 10.00),
    (2, 'Festival Tecnológico', 15.00),
    (3, 'Último Asiento Demo', 20.00)
ON CONFLICT (id) DO NOTHING;

INSERT INTO inventory (event_id, available)
VALUES
    (1, 100),
    (2, 50),
    (3, 1)
ON CONFLICT (event_id) DO NOTHING;
