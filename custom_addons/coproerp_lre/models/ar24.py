"""Chiffrement de l'API AR24 (signature des requêtes, déchiffrement des réponses).

Documentation AR24 : la signature est le chiffrement AES-256-CBC de la date de la requête,
avec pour clé sha256(clé privée) et pour vecteur d'initialisation les 16 premiers caractères de
sha256(sha256(clé privée)). Les réponses sont chiffrées avec la clé sha256(date + clé privée)
et le même vecteur. (Clés hexadécimales tronquées à 32 caractères, comme le fait PHP/OpenSSL.)
"""

import base64
import hashlib
import json

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def _sha(texte):
    return hashlib.sha256(texte.encode()).hexdigest()


def _iv(cle_privee):
    return _sha(_sha(cle_privee))[:16].encode()


def _chiffrer(texte, cle, iv):
    bourreur = padding.PKCS7(128).padder()
    donnees = bourreur.update(texte.encode()) + bourreur.finalize()
    chiffreur = Cipher(algorithms.AES(cle), modes.CBC(iv)).encryptor()
    return base64.b64encode(chiffreur.update(donnees) + chiffreur.finalize()).decode()


def _dechiffrer(texte, cle, iv):
    dechiffreur = Cipher(algorithms.AES(cle), modes.CBC(iv)).decryptor()
    brut = dechiffreur.update(base64.b64decode(texte)) + dechiffreur.finalize()
    debourreur = padding.PKCS7(128).unpadder()
    return (debourreur.update(brut) + debourreur.finalize()).decode()


def signature(date, cle_privee):
    return _chiffrer(date, _sha(cle_privee)[:32].encode(), _iv(cle_privee))


def chiffrer_reponse(contenu, date, cle_privee):
    """Inverse de lire_reponse (sert aux tests)."""
    return _chiffrer(json.dumps(contenu), _sha(date + cle_privee)[:32].encode(), _iv(cle_privee))


def lire_reponse(corps, date, cle_privee):
    """Réponse AR24 → dict. Les erreurs arrivent en JSON clair, les succès chiffrés."""
    corps = (corps or "").strip()
    try:
        donnees = json.loads(corps)
    except ValueError:
        donnees = None
    if isinstance(donnees, dict):
        return donnees
    try:
        return json.loads(_dechiffrer(corps, _sha(date + cle_privee)[:32].encode(), _iv(cle_privee)))
    except Exception:
        raise ValueError("Réponse d'AR24 illisible (clé privée incorrecte ?) : %s" % corps[:200]) from None
