CREATE TABLE users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('reporter','reviewer','signer','analyst','method','approver','technical')),
    scope TEXT NOT NULL,
    password TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE sessions (
    token TEXT PRIMARY KEY,
    actor TEXT NOT NULL REFERENCES users(id),
    expires INTEGER NOT NULL
);
CREATE TABLE regions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('dgd','ctl'))
);
CREATE TABLE methods (
    id TEXT PRIMARY KEY,
    track TEXT NOT NULL CHECK(track IN ('demo','source')),
    parent TEXT REFERENCES methods(id),
    name TEXT NOT NULL,
    effective TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','review','approved','published')),
    author TEXT NOT NULL REFERENCES users(id),
    approver TEXT REFERENCES users(id),
    created TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE TABLE periods (
    track TEXT NOT NULL,
    period TEXT NOT NULL,
    kind TEXT NOT NULL,
    method TEXT NOT NULL REFERENCES methods(id),
    PRIMARY KEY(track,period,kind)
);
CREATE TABLE packages (
    id TEXT PRIMARY KEY,
    track TEXT NOT NULL,
    period TEXT NOT NULL,
    kind TEXT NOT NULL,
    region TEXT NOT NULL REFERENCES regions(id),
    department TEXT NOT NULL,
    method TEXT NOT NULL REFERENCES methods(id),
    revision INTEGER NOT NULL,
    generation INTEGER NOT NULL DEFAULT 0,
    parent TEXT REFERENCES packages(id),
    status TEXT NOT NULL CHECK(status IN ('draft','submitted','returned','checked','signed')),
    facts TEXT NOT NULL,
    notes TEXT NOT NULL,
    signature TEXT,
    updated TEXT NOT NULL,
    UNIQUE(track,period,kind,region,department,revision),
    FOREIGN KEY(track,period,kind) REFERENCES periods(track,period,kind)
);
CREATE INDEX package_lookup ON packages(track,period,kind,region);
CREATE TABLE attachments (
    id TEXT PRIMARY KEY,
    package TEXT NOT NULL REFERENCES packages(id),
    component TEXT NOT NULL,
    name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    content BYTEA NOT NULL
);
CREATE TABLE deputies (
    id TEXT PRIMARY KEY,
    region TEXT NOT NULL REFERENCES regions(id),
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    starts TEXT NOT NULL,
    ends TEXT,
    assignments TEXT NOT NULL
);
CREATE TABLE results (
    id TEXT PRIMARY KEY,
    track TEXT NOT NULL,
    period TEXT NOT NULL,
    kind TEXT NOT NULL,
    region TEXT NOT NULL,
    method TEXT NOT NULL REFERENCES methods(id),
    revision INTEGER NOT NULL,
    created TEXT NOT NULL,
    content TEXT NOT NULL,
    UNIQUE(track,period,kind,region,revision)
);
CREATE TABLE settings (
    id TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE audit (
    id TEXT PRIMARY KEY,
    actor TEXT NOT NULL REFERENCES users(id),
    happened TEXT NOT NULL,
    object TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE INDEX audit_object ON audit(object,happened);

