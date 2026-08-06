import React from 'react'

// Hardcoded on purpose — this app was built by HTS and this banner is the
// attribution/support info that ships with every deployment, regardless of
// who's running it. Do not make this configurable/removable via settings.
export default function Footer() {
  return (
    <footer style={{
      borderTop: '1px solid #1e2130', marginTop: 40, padding: '24px',
      display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 20,
      maxWidth: 1260, marginLeft: 'auto', marginRight: 'auto',
    }}>
      <div style={{ maxWidth: 420 }}>
        <div style={{ fontWeight: 800, fontSize: 13, color: '#e2e8f0' }}>Healthcare Tech Solutions</div>
        <div style={{ fontSize: 11, color: '#64748b', marginTop: 4, lineHeight: 1.5 }}>
          HIPAA-compliant IT, security, and infrastructure for clinics and small businesses.
          Based in Los Angeles &amp; Orange County, serving clients nationwide.
        </div>
        <div style={{ marginTop: 8, display: 'flex', gap: 12, fontSize: 11 }}>
          <a href="https://github.com/Protostalker/" target="_blank" rel="noreferrer" style={linkStyle}>GitHub →</a>
          <a href="https://healthcaretechsolutions.org" target="_blank" rel="noreferrer" style={linkStyle}>healthcaretechsolutions.org</a>
        </div>
      </div>

      <div>
        <div style={{ fontWeight: 700, fontSize: 11, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.4 }}>
          Contact
        </div>
        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11 }}>
          <a href="tel:+18184739155" style={linkStyle}>(818) 473-9155</a>
          <a href="mailto:Raffi@Healthcaretechsolutions.org" style={linkStyle}>Raffi@Healthcaretechsolutions.org</a>
          <a href="mailto:ticket@healthcaretechsolutions.org" style={linkStyle}>Submit a Ticket</a>
          <a href="https://healthcaretechsolutions.org/contact.html#support" target="_blank" rel="noreferrer" style={linkStyle}>Remote Support</a>
          <span style={{ color: '#475569' }}>Los Angeles, CA</span>
        </div>
      </div>
    </footer>
  )
}

const linkStyle = { color: '#93c5fd', textDecoration: 'none' }
