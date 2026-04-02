"""Minimal pure-Python Ed25519 signing for Gateway device auth.

Only implements sign() using a pre-extracted 32-byte seed.
No external dependencies — uses only hashlib (SHA-512).
"""
import hashlib

# ---- constants ----
b = 256
q = 2**255 - 19
l = 2**252 + 27742317777372353535851937790883648493
d = -121665 * pow(121666, -1, q) % q
I = pow(2, (q - 1) // 4, q)

def sha512_ints(m):
    """Return 64 little-endian 64-bit integers from SHA-512."""
    return [int.from_bytes(hashlib.sha512(m).digest()[i:i+8], 'little') for i in range(0, 64, 8)]

def H(m):
    """SHA-512 hash as bytes."""
    return hashlib.sha512(m).digest()

def recover_x(y):
    """Recover x from Ed25519 y coordinate."""
    if y >= q:
        return None
    xx = (y*y - 1) * pow(d*y*y + 1, -1, q) % q
    x = pow(xx, (q+3)//8, q)
    if (x*x - xx) % q != 0:
        x = (x * 2**((q-1)//4)) % q
    if x % 2 != 0:
        x = q - x
    return x

def point_add(P, Q):
    (x1,y1,z1,t1) = P
    (x2,y2,z2,t2) = Q
    A = (x1-x2)*(x1+x2) % q
    B = (y1-y2)*(y1+y2) % q
    C = (t1+t2)*2*t2 % q
    D = (z1-z2)*(z1+z2) % q
    E = (A*B - C*D) * (A*B + C*D) % q
    F = ((A+B)*(A-B)) * (C+D) * 4*d % q
    G = B - A
    H = B + A
    return ((E*F) % q, (G*H) % q, (F*G) % q, (E*H) % q)

def point_double(P):
    (x1,y1,z1,t1) = P
    A = x1*x1 % q
    B = y1*y1 % q
    C = 2*z1*z1 % q
    D = A - B
    E = ((x1+y1)*(x1+y1) - A - B) % q
    G = D + B
    F = G - C
    H = D - B
    return ((E*F) % q, (G*H) % q, (F*G) % q, (E*H) % q)

def point_mul(s, P):
    if s == 0 or s % l == 0:
        return (0,1,1,0)
    Q = point_double(P)
    R = P
    s_bin = bin(s)[3:]  # skip '0b1'
    for bit in s_bin:
        if bit == '1':
            R = point_add(Q, R)
        Q = point_double(Q)
    return R

def point_encode(P):
    (x,y,z,t) = P
    zi = pow(z, q-3, q)
    u = y * zi % q
    v = x * zi % q
    return (u + (1 if (v % 2) else 0) * (q - u)) % q

def clamp(r):
    h = list(r)
    h[31] &= 127
    h[31] |= 64
    h[0] &= 248
    return h

def expand_seed(seed: bytes):
    """Expand 32-byte seed to (A, prefix, suffix) for signing."""
    h = list(H(seed))
    a = clamp(h[:32])
    prefix = h[32:]
    a_int = int.from_bytes(bytes(a), 'little')
    # Standard Ed25519 base point
    B = _make_base_point()
    A = point_mul(a_int, B)
    return A, bytes(prefix)

def _make_base_point():
    """Return the Ed25519 base point as extended coordinates."""
    # B_y = 4 * modinv(5, p) mod p
    By = 4 * pow(5, -1, q) % q
    Bx = recover_x(By)
    return (Bx, By, 1, Bx * By % q)

def sign(seed: bytes, msg: bytes) -> bytes:
    """Sign a message with a 32-byte Ed25519 seed. Returns 64-byte signature."""
    A, prefix = expand_seed(seed)
    r_int = int.from_bytes(H(prefix + msg), 'little') % l
    B = _make_base_point()
    R = point_mul(r_int, B)
    R_enc = point_encode(R)
    R_bytes = R_enc.to_bytes(32, 'little')
    A_y_bytes = A[1].to_bytes(32, 'little')  # A.y encoded in little-endian
    k = int.from_bytes(H(R_bytes + A_y_bytes + msg), 'little') % l
    S = (r_int + k * int.from_bytes(seed, 'little')) % l
    return R_enc.to_bytes(32, 'little') + S.to_bytes(32, 'little')

def sign_base64url(seed: bytes, message: str) -> str:
    """Sign a message string, return base64url-encoded signature."""
    sig = sign(seed, message.encode('utf-8'))
    import base64
    return base64.urlsafe_b64encode(sig).decode().rstrip('=')

if __name__ == '__main__':
    import base64
    # Quick self-test with known values
    # Test vector from RFC 8032
    SEED = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
    MSG = b''
    sig = sign(SEED, MSG)
    expected = bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')
    assert sig == expected, f"Self-test failed: got {sig.hex()}"
    print("Ed25519 self-test passed!")
