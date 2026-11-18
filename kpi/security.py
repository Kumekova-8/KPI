from datetime import datetime, timezone
from hashlib import pbkdf2_hmac, sha256
from hmac import compare_digest
import secrets
import time
from uuid import uuid4

from .db import encode


class Problem(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def require(condition,status,message):
    if not condition:
        raise Problem(status,message)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def uid():
    return uuid4().hex


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),230000)
    return f'{salt}:{digest.hex()}'


def password_matches(password, hashed):
    if not isinstance(password,str) or not 1 <= len(password) <= 128:
        return False
    salt,digest = hashed.split(':')
    candidate = pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),230000)
    return compare_digest(digest,candidate.hex())


DUMMY = password_hash('invalid-account')


def audit(tx,actor,object_id,action,detail=None):
    tx.insert('audit',{'id':uid(),'actor':actor,'happened':now(),'object':object_id,
                       'action':action,'detail':encode(detail or {})})


def login(tx,username,password):
    user = tx.one('SELECT * FROM users WHERE id=?',(str(username),))
    matches = password_matches(password,user['password'] if user is not None else DUMMY)
    require(matches and user and user['active'],401,'Проверьте логин и пароль.')
    cookie = secrets.token_urlsafe(32)
    expires = int(time.time()) + 8*3600
    tx.query('DELETE FROM sessions WHERE expires<?',(int(time.time()),))
    tx.insert('sessions',{'token':digest(cookie),'actor':user['id'],'expires':expires})
    audit(tx,user['id'],user['id'],'login')
    return cookie,public_user(user)


def digest(value):
    return sha256(value.encode() if isinstance(value,str) else value).hexdigest()


def actor(tx,cookie):
    require(cookie,401,'Войдите в систему.')
    user = tx.one('SELECT users.* FROM users JOIN sessions ON sessions.actor=users.id '
                  'WHERE token=? AND expires>? AND users.active=1',(digest(cookie),int(time.time())))
    require(user,401,'Войдите в систему.')
    return user


def role(user,*roles):
    require(user['role'] in roles,403,'Недостаточно прав для этого действия.')


def public_user(user):
    return {key:user[key] for key in ('id','name','role','scope','active')}

