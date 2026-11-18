"""Contracts for source connectors and signature verification."""
from typing import Protocol

from .db import encode
from .security import digest, now


class SourceConnector(Protocol):
    def fetch(self, region: str, period: str, kind: str, codes: list[str]) -> dict:
        """Return source inputs with provenance and an observation timestamp."""
        ...


class SignatureVerifier(Protocol):
    def verify(self, canonical_payload: bytes, cms: bytes, signer: dict) -> dict:
        """Validate CMS signature, trust chain, certificate usage and revocation."""
        ...


class NcaLayerVerifier:
    def verify(self, canonical_payload, cms, signer):
        raise NotImplementedError('Требуется настройка доверенной среды НУЦ РК и серверного валидатора CMS.')


class SyntheticSource:
    def fetch(self, region, period, kind, codes):
        sample = {'S001':{'A':'104.2','B':'100'},'S081':{'A':'97','B':'100'}}
        return {code:{'values':sample[code],'source':'Синтетический источник','observed':now()}
                for code in codes if code in sample}


def demonstration_signature(payload, signer):
    return {'label':'Демонстрационная подпись','mode':'demo','sha256':digest(encode(payload)),
            'actor':signer,'timestamp':now()}

