from app.core.security import decrypt_secret, encrypt_secret, hash_password, mask_key, verify_password


def test_password_hash_and_verify():
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_encrypt_secret_round_trip_and_mask():
    encrypted = encrypt_secret("sk-secret-value", "app-secret")

    assert encrypted != "sk-secret-value"
    assert decrypt_secret(encrypted, "app-secret") == "sk-secret-value"
    assert mask_key("sk-secret-value") == "sk-secr...-value"

