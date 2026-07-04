CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    full_name TEXT NOT NULL,

    email TEXT UNIQUE NOT NULL,

    phone TEXT,

    dob TEXT,

    password TEXT NOT NULL,

    plan TEXT DEFAULT 'FREE',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);


