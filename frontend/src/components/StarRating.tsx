interface Props {
  stars: number
  onChange?: (stars: number) => void
}

export default function StarRating({ stars, onChange }: Props) {
  return (
    <span className={`stars ${onChange ? '' : 'readonly'}`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span
          key={n}
          className={`star ${n <= stars ? 'on' : ''}`}
          onClick={(e) => {
            e.stopPropagation()
            // Clicking the current rating clears it, Lightroom-style.
            onChange?.(n === stars ? 0 : n)
          }}
        >
          ★
        </span>
      ))}
    </span>
  )
}
