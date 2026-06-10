-- Small SQL example to exercise the kgr SQL extractor.
CREATE TABLE shop.customers (
    customer_id INT NOT NULL,
    email       VARCHAR(256) NOT NULL,
    created_at  TIMESTAMP NOT NULL
);

CREATE TABLE shop.orders (
    order_id    INT NOT NULL,
    customer_id INT NOT NULL,
    total       DECIMAL(12, 2) NOT NULL,
    placed_at   TIMESTAMP NOT NULL
);

CREATE VIEW shop.recent_orders AS
SELECT o.order_id, o.total, c.email
FROM shop.orders o
JOIN shop.customers c ON c.customer_id = o.customer_id
WHERE o.placed_at > CURRENT_TIMESTAMP - INTERVAL '7' DAY;

INSERT INTO shop.orders (order_id, customer_id, total, placed_at)
VALUES (1, 1, 19.99, CURRENT_TIMESTAMP);
