# Security Policy

## Supported Versions

We provide security updates for the following versions of PyWebTransport:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take the security of PyWebTransport seriously. If you believe you have found a security vulnerability, please report it to us responsibly.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to:

**Email**: lemonsterfy@gmail.com  
**Subject**: [SECURITY] PyWebTransport Security Report

### What to Include

Please include the following information in your report:

- **Description**: A clear description of the vulnerability
- **Impact**: Potential impact and attack scenarios
- **Reproduction**: Step-by-step instructions to reproduce the issue
- **Environment**: Python version, PyWebTransport version, and operating system
- **Proof of Concept**: If possible, include a minimal code example

### Response Timeline

- **Acknowledgment**: We will acknowledge receipt of your report within 48 hours
- **Initial Assessment**: We will provide an initial assessment within 5 business days
- **Resolution**: We aim to resolve critical vulnerabilities within 30 days

### Disclosure Policy

- We follow responsible disclosure practices
- We will work with you to understand and resolve the issue
- We will credit you in our security advisory (unless you prefer to remain anonymous)
- We will coordinate public disclosure after a fix is available

## Security Considerations

### WebTransport Protocol Security

PyWebTransport implements the WebTransport protocol which includes several security features:

- **TLS 1.3 Encryption**: All connections use TLS 1.3 for transport security
- **Certificate Validation**: Default configuration requires valid TLS certificates
- **QUIC Security**: Built on QUIC protocol with integrated encryption

### Common Security Best Practices

When using PyWebTransport in production:

#### Server Configuration

- Use valid TLS certificates from a trusted Certificate Authority
- Configure appropriate cipher suites and TLS versions
- Implement proper access controls and authentication
- Regularly update certificates before expiration

#### Client Configuration

- Enable certificate verification in production (`verify_mode=ssl.CERT_REQUIRED`)
- Validate server certificates and hostnames
- Use secure credential storage for client certificates
- Implement connection timeouts and retry limits

#### Network Security

- Use firewalls to restrict access to WebTransport ports
- Monitor connections for unusual patterns
- Implement rate limiting and DDoS protection
- Log security-relevant events for auditing

### Known Security Considerations

- **Development Certificates**: Never use self-signed certificates in production
- **Certificate Validation**: Disabling certificate verification creates security risks
- **Connection Limits**: Configure appropriate connection and stream limits
- **Input Validation**: Always validate and sanitize data received over WebTransport

## Dependencies

PyWebTransport relies on the following security-critical dependencies:

- **aioquic**: QUIC protocol implementation
- **cryptography**: Cryptographic operations
- **OpenSSL**: TLS/SSL functionality

We monitor these dependencies for security updates and will update PyWebTransport accordingly.

## Security Updates

Security updates will be:

- Released as patch versions (e.g., 0.1.1 → 0.1.2)
- Documented in our changelog with security tags
- Announced through GitHub security advisories
- Available immediately upon release

## Bug Bounty

We currently do not offer a formal bug bounty program, but we greatly appreciate security researchers who help improve the security of PyWebTransport.

## Contact

For any security-related questions or concerns:

- **Security Reports**: lemonsterfy@gmail.com
- **General Security Questions**: GitHub Discussions
- **Project Maintainer**: lemonsterfy

---

Thank you for helping keep PyWebTransport and the WebTransport ecosystem secure.
