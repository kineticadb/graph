-- Retail mini-warehouse: raw landing schema, analytics schema, a few views and queries.
-- Exercises: multi-schema, table/column DEFINES, view DERIVES_FROM, query READS/WRITES,
-- CTEs, joins, aggregation, UPDATE, DELETE, INSERT FROM SELECT.
-- Notes for kgr: FK constraints are declared but not yet modeled as edges.

CREATE TABLE raw.customers (
    customer_id   BIGINT       NOT NULL,
    email         VARCHAR(256) NOT NULL,
    country_code  CHAR(2)      NOT NULL,
    signup_ts     TIMESTAMP    NOT NULL
);

CREATE TABLE raw.products (
    product_id   BIGINT       NOT NULL,
    sku          VARCHAR(64)  NOT NULL,
    title        VARCHAR(512) NOT NULL,
    category     VARCHAR(64)  NOT NULL,
    list_price   DECIMAL(10,2) NOT NULL
);

CREATE TABLE raw.orders (
    order_id     BIGINT       NOT NULL,
    customer_id  BIGINT       NOT NULL,
    placed_ts    TIMESTAMP    NOT NULL,
    status       VARCHAR(16)  NOT NULL
);

CREATE TABLE raw.order_items (
    order_item_id BIGINT       NOT NULL,
    order_id      BIGINT       NOT NULL,
    product_id    BIGINT       NOT NULL,
    quantity      INT          NOT NULL,
    unit_price    DECIMAL(10,2) NOT NULL
);

-- Analytics layer

CREATE VIEW analytics.order_revenue AS
SELECT
    o.order_id,
    o.customer_id,
    o.placed_ts,
    SUM(oi.quantity * oi.unit_price) AS revenue
FROM raw.orders o
JOIN raw.order_items oi ON oi.order_id = o.order_id
GROUP BY o.order_id, o.customer_id, o.placed_ts;

CREATE VIEW analytics.customer_ltv AS
SELECT
    c.customer_id,
    c.country_code,
    COUNT(DISTINCT r.order_id) AS orders,
    SUM(r.revenue)             AS lifetime_value
FROM raw.customers c
LEFT JOIN analytics.order_revenue r ON r.customer_id = c.customer_id
GROUP BY c.customer_id, c.country_code;

CREATE VIEW analytics.top_categories AS
WITH item_lines AS (
    SELECT p.category, oi.quantity * oi.unit_price AS line_revenue
    FROM raw.order_items oi
    JOIN raw.products p ON p.product_id = oi.product_id
)
SELECT category, SUM(line_revenue) AS revenue
FROM item_lines
GROUP BY category;

-- Daily DML the pipeline would actually run

INSERT INTO raw.customers (customer_id, email, country_code, signup_ts)
SELECT customer_id, email, country_code, signup_ts
FROM staging.new_customers
WHERE signup_ts >= CURRENT_DATE;

UPDATE raw.orders
SET status = 'fulfilled'
WHERE order_id IN (SELECT order_id FROM staging.fulfillment_events);

DELETE FROM raw.order_items
WHERE order_id IN (SELECT order_id FROM raw.orders WHERE status = 'cancelled');

-- Ad-hoc analytical query (a query node with no write target)

SELECT c.country_code, SUM(l.lifetime_value) AS country_ltv
FROM analytics.customer_ltv l
JOIN raw.customers c ON c.customer_id = l.customer_id
GROUP BY c.country_code;
