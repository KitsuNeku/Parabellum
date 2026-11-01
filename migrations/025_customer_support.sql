CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id        SERIAL PRIMARY KEY,
    token_hash       CHAR(64) NOT NULL UNIQUE,
    company          VARCHAR(150),
    contact_name     VARCHAR(120) NOT NULL,
    email            VARCHAR(150) NOT NULL,
    phone            VARCHAR(40)  NOT NULL,
    order_ref        VARCHAR(60),
    transaction_id   INT REFERENCES transactions(transaction_id) ON DELETE SET NULL,
    status           VARCHAR(12)  NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','Answered','Closed')),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    staff_read_at    TIMESTAMPTZ,
    customer_read_at TIMESTAMPTZ,
    closed_at        TIMESTAMPTZ,
    closed_by        VARCHAR(120)
);
CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS support_messages (
    message_id     SERIAL PRIMARY KEY,
    ticket_id      INT NOT NULL REFERENCES support_tickets(ticket_id) ON DELETE CASCADE,
    sender         VARCHAR(10) NOT NULL CHECK (sender IN ('customer','staff')),
    staff_user_id  INT REFERENCES users(user_id) ON DELETE SET NULL,
    staff_name     VARCHAR(120),
    body           TEXT NOT NULL,
    sent_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_support_messages_ticket ON support_messages (ticket_id, message_id);

UPDATE role_permissions SET permissions = permissions || ',support'
 WHERE role IN ('System Administrator','Operations Personnel','Management/Owner')
   AND (',' || permissions || ',') NOT LIKE '%,support,%';

UPDATE users SET custom_permissions = custom_permissions || ',support'
 WHERE COALESCE(custom_permissions, '') <> ''
   AND (role IN ('System Administrator','Operations Personnel','Management/Owner')
        OR (',' || custom_permissions || ',') LIKE '%,transactions,%')
   AND (',' || custom_permissions || ',') NOT LIKE '%,support,%';
