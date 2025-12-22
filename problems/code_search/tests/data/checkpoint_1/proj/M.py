#!/usr/bin/env python3
"""
Advanced Cryptography and Security Module
Provides implementations of various cryptographic algorithms, security utilities,
and secure communication protocols for enterprise applications.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class EncryptionResult:
    """Container for encryption results."""

    ciphertext: bytes
    iv: bytes
    tag: bytes | None = None
    salt: bytes | None = None
    algorithm: str = ""
    key_size: int = 0


@dataclass
class DigitalSignature:
    """Container for digital signature data."""

    signature: bytes
    algorithm: str
    public_key: bytes
    timestamp: float


class CryptographyManager:
    """Main class for cryptographic operations."""

    def __init__(self):
        self.backend = default_backend()
        self.supported_algorithms = {
            "symmetric": ["AES-256-GCM", "AES-256-CBC", "ChaCha20-Poly1305"],
            "asymmetric": ["RSA-2048", "RSA-4096", "ECDSA-P256"],
            "hashing": ["SHA-256", "SHA-512", "BLAKE2b"],
        }

    def generate_secure_random(self, length: int = 32) -> bytes:
        """
        Generate cryptographically secure random bytes.

        Args:
            length: Number of random bytes to generate

        Returns:
            Secure random bytes
        """
        return secrets.token_bytes(length)

    def generate_password_hash(
        self,
        password: str,
        salt: bytes | None = None,
        iterations: int = 100000,
    ) -> tuple[str, bytes]:
        """
        Generate secure password hash using PBKDF2.

        Args:
            password: Plain text password
            salt: Optional salt (generated if not provided)
            iterations: Number of PBKDF2 iterations

        Returns:
            Tuple of (hashed_password, salt)
        """
        if salt is None:
            salt = self.generate_secure_random(32)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
            backend=self.backend,
        )

        hashed_password = kdf.derive(password.encode("utf-8"))
        return base64.b64encode(hashed_password).decode("utf-8"), salt

    def verify_password(
        self,
        password: str,
        hashed_password: str,
        salt: bytes,
        iterations: int = 100000,
    ) -> bool:
        """
        Verify password against stored hash.

        Args:
            password: Plain text password to verify
            hashed_password: Stored hashed password
            salt: Salt used for hashing
            iterations: Number of iterations used

        Returns:
            True if password matches, False otherwise
        """
        try:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=iterations,
                backend=self.backend,
            )

            kdf.verify(
                password.encode("utf-8"), base64.b64decode(hashed_password)
            )
            return True
        except Exception:
            return False

    def encrypt_aes_gcm(
        self, plaintext: str | bytes, key: bytes
    ) -> EncryptionResult:
        """
        Encrypt data using AES-256-GCM.

        Args:
            plaintext: Data to encrypt
            key: 32-byte encryption key

        Returns:
            EncryptionResult with ciphertext, IV, and authentication tag
        """
        if isinstance(plaintext, str):
            plaintext = plaintext.encode("utf-8")

        # Generate random IV
        iv = self.generate_secure_random(12)

        # Create cipher
        cipher = Cipher(
            algorithms.AES(key), modes.GCM(iv), backend=self.backend
        )
        encryptor = cipher.encryptor()

        # Encrypt and authenticate
        ciphertext = encryptor.update(plaintext) + encryptor.finalize()

        return EncryptionResult(
            ciphertext=ciphertext,
            iv=iv,
            tag=encryptor.tag,
            algorithm="AES-256-GCM",
            key_size=len(key) * 8,
        )

    def decrypt_aes_gcm(
        self, encryption_result: EncryptionResult, key: bytes
    ) -> bytes:
        """
        Decrypt AES-256-GCM encrypted data.

        Args:
            encryption_result: EncryptionResult from encrypt_aes_gcm
            key: 32-byte encryption key

        Returns:
            Decrypted plaintext
        """
        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(encryption_result.iv, encryption_result.tag),
            backend=self.backend,
        )
        decryptor = cipher.decryptor()

        plaintext = (
            decryptor.update(encryption_result.ciphertext)
            + decryptor.finalize()
        )
        return plaintext

    def encrypt_aes_cbc(
        self, plaintext: str | bytes, key: bytes
    ) -> EncryptionResult:
        """
        Encrypt data using AES-256-CBC with PKCS7 padding.

        Args:
            plaintext: Data to encrypt
            key: 32-byte encryption key

        Returns:
            EncryptionResult with ciphertext and IV
        """
        if isinstance(plaintext, str):
            plaintext = plaintext.encode("utf-8")

        # Generate random IV
        iv = self.generate_secure_random(16)

        # Create cipher
        cipher = Cipher(
            algorithms.AES(key), modes.CBC(iv), backend=self.backend
        )
        encryptor = cipher.encryptor()

        # Apply PKCS7 padding
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(plaintext) + padder.finalize()

        # Encrypt
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()

        return EncryptionResult(
            ciphertext=ciphertext,
            iv=iv,
            algorithm="AES-256-CBC",
            key_size=len(key) * 8,
        )

    def decrypt_aes_cbc(
        self, encryption_result: EncryptionResult, key: bytes
    ) -> bytes:
        """
        Decrypt AES-256-CBC encrypted data.

        Args:
            encryption_result: EncryptionResult from encrypt_aes_cbc
            key: 32-byte encryption key

        Returns:
            Decrypted plaintext
        """
        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(encryption_result.iv),
            backend=self.backend,
        )
        decryptor = cipher.decryptor()

        # Decrypt
        padded_plaintext = (
            decryptor.update(encryption_result.ciphertext)
            + decryptor.finalize()
        )

        # Remove padding
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

        return plaintext

    def generate_rsa_key_pair(
        self, key_size: int = 2048
    ) -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
        """
        Generate RSA key pair.

        Args:
            key_size: RSA key size in bits (2048 or 4096)

        Returns:
            Tuple of (private_key, public_key)
        """
        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=key_size, backend=self.backend
        )
        public_key = private_key.public_key()

        return private_key, public_key

    def serialize_private_key(
        self, private_key: rsa.RSAPrivateKey, password: str | None = None
    ) -> bytes:
        """
        Serialize private key to PEM format.

        Args:
            private_key: RSA private key
            password: Optional password for encryption

        Returns:
            PEM-encoded private key
        """
        encryption = serialization.NoEncryption()
        if password:
            encryption = serialization.BestAvailableEncryption(
                password.encode("utf-8")
            )

        return private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=encryption,
        )

    def serialize_public_key(self, public_key: rsa.RSAPublicKey) -> bytes:
        """
        Serialize public key to PEM format.

        Args:
            public_key: RSA public key

        Returns:
            PEM-encoded public key
        """
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def sign_data(
        self, data: str | bytes, private_key: rsa.RSAPrivateKey
    ) -> DigitalSignature:
        """
        Sign data using RSA private key.

        Args:
            data: Data to sign
            private_key: RSA private key

        Returns:
            DigitalSignature with signature and metadata
        """
        if isinstance(data, str):
            data = data.encode("utf-8")

        signature = private_key.sign(
            data,
            asym_padding.PSS(
                mgf=asym_padding.MGF1(hashes.SHA256()),
                salt_length=asym_padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        return DigitalSignature(
            signature=signature,
            algorithm="RSA-PSS-SHA256",
            public_key=self.serialize_public_key(private_key.public_key()),
            timestamp=time.time(),
        )

    def verify_signature(
        self,
        data: str | bytes,
        signature: DigitalSignature,
        public_key: rsa.RSAPublicKey,
    ) -> bool:
        """
        Verify digital signature.

        Args:
            data: Original data
            signature: DigitalSignature to verify
            public_key: RSA public key

        Returns:
            True if signature is valid, False otherwise
        """
        try:
            if isinstance(data, str):
                data = data.encode("utf-8")

            public_key.verify(
                signature.signature,
                data,
                asym_padding.PSS(
                    mgf=asym_padding.MGF1(hashes.SHA256()),
                    salt_length=asym_padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
            return True
        except Exception:
            return False

    def compute_hash(
        self, data: str | bytes, algorithm: str = "SHA-256"
    ) -> str:
        """
        Compute cryptographic hash of data.

        Args:
            data: Data to hash
            algorithm: Hash algorithm (SHA-256, SHA-512, BLAKE2b)

        Returns:
            Hexadecimal hash string
        """
        if isinstance(data, str):
            data = data.encode("utf-8")

        if algorithm == "SHA-256":
            hash_obj = hashlib.sha256(data)
        elif algorithm == "SHA-512":
            hash_obj = hashlib.sha512(data)
        elif algorithm == "BLAKE2b":
            hash_obj = hashlib.blake2b(data)
        else:
            raise ValueError(f"Unsupported hash algorithm: {algorithm}")

        return hash_obj.hexdigest()

    def compute_hmac(
        self, data: str | bytes, key: bytes, algorithm: str = "SHA-256"
    ) -> str:
        """
        Compute HMAC of data using secret key.

        Args:
            data: Data to authenticate
            key: Secret key for HMAC
            algorithm: Hash algorithm for HMAC

        Returns:
            Hexadecimal HMAC string
        """
        if isinstance(data, str):
            data = data.encode("utf-8")

        if algorithm == "SHA-256":
            hash_func = hashlib.sha256
        elif algorithm == "SHA-512":
            hash_func = hashlib.sha512
        else:
            raise ValueError(f"Unsupported HMAC algorithm: {algorithm}")

        hmac_obj = hmac.new(key, data, hash_func)
        return hmac_obj.hexdigest()

    def generate_key_from_password(
        self, password: str, salt: bytes | None = None, key_length: int = 32
    ) -> tuple[bytes, bytes]:
        """
        Derive encryption key from password using PBKDF2.

        Args:
            password: Password to derive key from
            salt: Optional salt (generated if not provided)
            key_length: Desired key length in bytes

        Returns:
            Tuple of (derived_key, salt)
        """
        if salt is None:
            salt = self.generate_secure_random(32)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=key_length,
            salt=salt,
            iterations=100000,
            backend=self.backend,
        )

        key = kdf.derive(password.encode("utf-8"))
        return key, salt

    def secure_compare(
        self, a: str | bytes, b: str | bytes
    ) -> bool:
        """
        Securely compare two strings/bytes to prevent timing attacks.

        Args:
            a: First value to compare
            b: Second value to compare

        Returns:
            True if values are equal, False otherwise
        """
        if isinstance(a, str):
            a = a.encode("utf-8")
        if isinstance(b, str):
            b = b.encode("utf-8")

        return hmac.compare_digest(a, b)

    def generate_jwt_token(
        self,
        payload: dict[str, Any],
        secret_key: str,
        algorithm: str = "HS256",
        expires_in: int = 3600,
    ) -> str:
        """
        Generate JWT token (simplified implementation).

        Args:
            payload: Token payload data
            secret_key: Secret key for signing
            algorithm: Signing algorithm
            expires_in: Token expiration time in seconds

        Returns:
            JWT token string
        """
        import base64

        # Create header
        header = {"alg": algorithm, "typ": "JWT"}

        # Add expiration to payload
        payload_copy = payload.copy()
        payload_copy["exp"] = int(time.time()) + expires_in
        payload_copy["iat"] = int(time.time())

        # Encode header and payload
        header_b64 = (
            base64.urlsafe_b64encode(json.dumps(header).encode())
            .decode()
            .rstrip("=")
        )
        payload_b64 = (
            base64.urlsafe_b64encode(json.dumps(payload_copy).encode())
            .decode()
            .rstrip("=")
        )

        # Create signature
        message = f"{header_b64}.{payload_b64}"
        signature = self.compute_hmac(message, secret_key.encode(), "SHA-256")
        signature_b64 = (
            base64.urlsafe_b64encode(signature.encode()).decode().rstrip("=")
        )

        return f"{message}.{signature_b64}"


class SecurityAuditLogger:
    """Logger for security-related events."""

    def __init__(self, log_file: str = "security_audit.log"):
        self.log_file = log_file
        self.logger = logging.getLogger("security_audit")
        handler = logging.FileHandler(log_file)
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def log_authentication_event(
        self, user_id: str, success: bool, ip_address: str, user_agent: str
    ) -> None:
        """Log authentication attempt."""
        status = "SUCCESS" if success else "FAILURE"
        self.logger.info(
            f"AUTH_{status} - User: {user_id}, IP: {ip_address}, UA: {user_agent}"
        )

    def log_data_access(self, user_id: str, resource: str, action: str) -> None:
        """Log data access event."""
        self.logger.info(
            f"DATA_ACCESS - User: {user_id}, Resource: {resource}, Action: {action}"
        )

    def log_encryption_event(
        self, operation: str, algorithm: str, key_size: int
    ) -> None:
        """Log encryption/decryption event."""
        self.logger.info(
            f"CRYPTO_{operation} - Algorithm: {algorithm}, Key Size: {key_size}"
        )

    def log_security_violation(
        self, violation_type: str, details: str, severity: str = "MEDIUM"
    ) -> None:
        """Log security violation."""
        self.logger.warning(
            f"SECURITY_VIOLATION - Type: {violation_type}, Severity: {severity}, Details: {details}"
        )


def main():
    """Example usage of the CryptographyManager class."""
    crypto = CryptographyManager()
    audit_logger = SecurityAuditLogger()

    try:
        # Generate encryption key
        key = crypto.generate_secure_random(32)
        print(f"Generated encryption key: {key.hex()}")

        # Encrypt and decrypt data
        plaintext = "This is a secret message that needs to be protected."
        encrypted = crypto.encrypt_aes_gcm(plaintext, key)
        print(f"Encrypted data length: {len(encrypted.ciphertext)} bytes")

        decrypted = crypto.decrypt_aes_gcm(encrypted, key)
        print(f"Decrypted: {decrypted.decode('utf-8')}")

        # Generate RSA key pair
        private_key, public_key = crypto.generate_rsa_key_pair(2048)
        print("Generated RSA key pair")

        # Sign and verify data
        signature = crypto.sign_data(plaintext, private_key)
        is_valid = crypto.verify_signature(plaintext, signature, public_key)
        print(f"Signature verification: {is_valid}")

        # Password hashing
        password = "SecurePassword123!"
        hashed_password, salt = crypto.generate_password_hash(password)
        is_password_valid = crypto.verify_password(
            password, hashed_password, salt
        )
        print(f"Password verification: {is_password_valid}")

        # Compute hash
        data_hash = crypto.compute_hash(plaintext, "SHA-256")
        print(f"SHA-256 hash: {data_hash}")

        # Generate JWT token
        payload = {"user_id": "user123", "role": "admin"}
        token = crypto.generate_jwt_token(payload, "secret_key")
        print(f"Generated JWT token: {token[:50]}...")

        # Log security events
        audit_logger.log_authentication_event(
            "user123", True, "192.168.1.100", "Mozilla/5.0"
        )
        audit_logger.log_encryption_event("ENCRYPT", "AES-256-GCM", 256)
        audit_logger.log_data_access("user123", "/api/v1/users", "READ")

        print("Security operations completed successfully")

    except Exception as e:
        audit_logger.log_security_violation(
            "CRYPTOGRAPHY_ERROR", str(e), "HIGH"
        )
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
