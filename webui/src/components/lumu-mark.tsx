interface Props {
  size?: number
  className?: string
}

export function LumuMark({ size = 22, className = '' }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={className}
      fill="none"
      aria-hidden="true"
    >
      <circle cx="16" cy="16" r="11" stroke="#7fdcff" strokeWidth="1.6" />
      <circle cx="16" cy="16" r="11" stroke="#7fdcff" strokeWidth="3" strokeOpacity="0.15" />
      <circle cx="12.6" cy="14" r="1.8" fill="#ffb454" />
      <circle cx="19.4" cy="14" r="1.8" fill="#ffb454" />
      <ellipse
        cx="16"
        cy="16"
        rx="13"
        ry="5"
        stroke="#7fdcff"
        strokeWidth="1"
        strokeOpacity="0.5"
        transform="rotate(-25 16 16)"
      />
      <circle cx="27.2" cy="10.6" r="1.5" fill="#7fdcff" />
    </svg>
  )
}
