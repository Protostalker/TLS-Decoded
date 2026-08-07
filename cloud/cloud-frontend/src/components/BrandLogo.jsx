import React from 'react'

// Mirrors frontend/src/components/BrandLogo.jsx — shows a station's uploaded
// logo if it mirrored one up, otherwise a generated monogram badge using the
// mirrored primary/secondary colors. Not an attempt at reproducing any real
// company's logo artwork.
export default function BrandLogo({ logoDataUrl, initial = 'T', size = 32 }) {
  if (logoDataUrl) {
    return (
      <img
        src={logoDataUrl} alt="Station logo"
        style={{ width: size, height: size, borderRadius: 8, objectFit: 'contain', background: '#fff' }}
      />
    )
  }
  return (
    <div style={{
      width: size, height: size, borderRadius: 8,
      background: 'linear-gradient(135deg, var(--brand-primary, #3b82f6), var(--brand-secondary, #6366f1))',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: Math.round(size * 0.56), fontWeight: 800, color: '#fff',
    }}>
      {initial}
    </div>
  )
}
