# Copyright 2014 Rackspace US, Inc
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import datetime

from cryptography import exceptions as crypto_exceptions
from cryptography.hazmat import backends
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography import x509

import octavia.certificates.generator.local as local_cert_gen
import octavia.tests.unit.base as base


class TestLocalGenerator(base.TestCase):
    def setUp(self):
        self.signing_digest = "sha256"

        # Set up CSR data
        csr_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=backends.default_backend()
        )
        csr = x509.CertificateSigningRequestBuilder().subject_name(
            x509.Name([
                x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, u"test"),
            ])).sign(csr_key, hashes.SHA256(), backends.default_backend())
        self.certificate_signing_request = csr.public_bytes(
            serialization.Encoding.PEM)

        # Set up CA data
        ca_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=backends.default_backend()
        )

        self.ca_private_key_passphrase = b"Testing"
        self.ca_private_key = ca_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.BestAvailableEncryption(
                self.ca_private_key_passphrase),
        )

        ca_cert = x509.CertificateBuilder()
        valid_from_datetime = datetime.datetime.utcnow()
        valid_until_datetime = (datetime.datetime.utcnow() +
                                datetime.timedelta(
            seconds=2 * 365 * 24 * 60 * 60))
        ca_cert = ca_cert.not_valid_before(valid_from_datetime)
        ca_cert = ca_cert.not_valid_after(valid_until_datetime)
        ca_cert = ca_cert.serial_number(1)
        subject_name = x509.Name([
            x509.NameAttribute(x509.oid.NameOID.COUNTRY_NAME, u"US"),
            x509.NameAttribute(x509.oid.NameOID.STATE_OR_PROVINCE_NAME,
                               u"Oregon"),
            x509.NameAttribute(x509.oid.NameOID.LOCALITY_NAME, u"Springfield"),
            x509.NameAttribute(x509.oid.NameOID.ORGANIZATION_NAME,
                               u"Springfield Nuclear Power Plant"),
            x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, u"maggie1"),
        ])
        ca_cert = ca_cert.subject_name(subject_name)
        ca_cert = ca_cert.issuer_name(subject_name)
        ca_cert = ca_cert.public_key(ca_key.public_key())
        signed_cert = ca_cert.sign(private_key=ca_key,
                                   algorithm=hashes.SHA256(),
                                   backend=backends.default_backend())

        self.ca_certificate = signed_cert.public_bytes(
            encoding=serialization.Encoding.PEM)

        super(TestLocalGenerator, self).setUp()

    def test_sign_cert(self):
        # Attempt sign a cert
        signed_cert = local_cert_gen.LocalCertGenerator.sign_cert(
            csr=self.certificate_signing_request,
            validity=2 * 365 * 24 * 60 * 60,
            ca_cert=self.ca_certificate,
            ca_key=self.ca_private_key,
            ca_key_pass=self.ca_private_key_passphrase,
            ca_digest=self.signing_digest
        )

        self.assertIn("-----BEGIN CERTIFICATE-----",
                      signed_cert.decode('ascii'))

        # Load the cert for specific tests
        cert = x509.load_pem_x509_certificate(
            data=signed_cert, backend=backends.default_backend())

        # Make sure expiry time is accurate
        should_expire = (datetime.datetime.utcnow() +
                         datetime.timedelta(seconds=2 * 365 * 24 * 60 * 60))
        diff = should_expire - cert.not_valid_after
        self.assertTrue(diff < datetime.timedelta(seconds=10))

        # Make sure this is a version 3 X509.
        self.assertEqual('v3', cert.version.name)

        # Make sure this cert is marked as Server and Client Cert via the
        # The extended Key Usage extension
        self.assertIn(x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                      cert.extensions.get_extension_for_class(
                          x509.ExtendedKeyUsage).value._usages)
        self.assertIn(x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                      cert.extensions.get_extension_for_class(
                          x509.ExtendedKeyUsage).value._usages)

        # Make sure this cert can't sign other certs
        self.assertFalse(cert.extensions.get_extension_for_class(
            x509.BasicConstraints).value.ca)

    def test_sign_cert_invalid_algorithm(self):
        self.assertRaises(
            crypto_exceptions.UnsupportedAlgorithm,
            local_cert_gen.LocalCertGenerator.sign_cert,
            csr=self.certificate_signing_request,
            validity=2 * 365 * 24 * 60 * 60,
            ca_cert=self.ca_certificate,
            ca_key=self.ca_private_key,
            ca_key_pass=self.ca_private_key_passphrase,
            ca_digest='not_an_algorithm'
        )

    def test_generate_private_key(self):
        bit_length = 1024
        # Attempt to generate a private key
        pk = local_cert_gen.LocalCertGenerator._generate_private_key(
            bit_length=bit_length
        )

        # Attempt to load the generated private key
        pko = serialization.load_pem_private_key(
            data=pk, password=None, backend=backends.default_backend())

        # Make sure the bit_length is what we set
        self.assertEqual(pko.key_size, bit_length)

    def test_generate_private_key_with_passphrase(self):
        bit_length = 2048
        # Attempt to generate a private key
        pk = local_cert_gen.LocalCertGenerator._generate_private_key(
            bit_length=bit_length,
            passphrase=self.ca_private_key_passphrase
        )

        # Attempt to load the generated private key
        pko = serialization.load_pem_private_key(
            data=pk, password=self.ca_private_key_passphrase,
            backend=backends.default_backend())

        # Make sure the bit_length is what we set
        self.assertEqual(pko.key_size, bit_length)

    def test_generate_csr(self):
        cn = 'test_cn'
        # Attempt to generate a CSR
        csr = local_cert_gen.LocalCertGenerator._generate_csr(
            cn=cn,
            private_key=self.ca_private_key,
            passphrase=self.ca_private_key_passphrase
        )

        # Attempt to load the generated CSR
        csro = x509.load_pem_x509_csr(data=csr,
                                      backend=backends.default_backend())

        # Make sure the CN is correct
        self.assertEqual(cn, csro.subject.get_attributes_for_oid(
            x509.oid.NameOID.COMMON_NAME)[0].value)

    def test_generate_cert_key_pair(self):
        cn = 'test_cn'
        bit_length = 512
        # Attempt to generate a cert/key pair
        cert_object = local_cert_gen.LocalCertGenerator.generate_cert_key_pair(
            cn=cn,
            validity=2 * 365 * 24 * 60 * 60,
            bit_length=bit_length,
            passphrase=self.ca_private_key_passphrase,
            ca_cert=self.ca_certificate,
            ca_key=self.ca_private_key,
            ca_key_pass=self.ca_private_key_passphrase
        )

        # Validate that the cert and key are loadable
        cert = x509.load_pem_x509_certificate(
            data=cert_object.certificate, backend=backends.default_backend())
        self.assertIsNotNone(cert)

        key = serialization.load_pem_private_key(
            data=cert_object.private_key,
            password=cert_object.private_key_passphrase,
            backend=backends.default_backend())
        self.assertIsNotNone(key)
