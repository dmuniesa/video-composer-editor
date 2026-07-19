import { useState } from 'react'
import { IcStar } from './icons'

interface Props {
  stars: number
  onChange?: (stars: number) => void
}

export default function StarRating({ stars, onChange }: Props) {
  const [hover, setHover] = useState(0)
  // While hovering, preview the rating the click would set.
  const active = hover || stars
  return (
    <span
      className={`stars ${onChange ? '' : 'readonly'}`}
      onMouseLeave={() => setHover(0)}
    >
      {[1, 2, 3, 4, 5].map((n) => (
        <span
          key={n}
          className={`star ${n <= active ? 'on' : ''} ${hover ? 'preview' : ''}`}
          onMouseEnter={onChange ? () => setHover(n) : undefined}
          onClick={(e) => {
            e.stopPropagation()
            // Clicking the current rating clears it, Lightroom-style.
            onChange?.(n === stars ? 0 : n)
          }}
        >
          <IcStar filled={n <= active} />
        </span>
      ))}
    </span>
  )
}
