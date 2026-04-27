export function LunaMark({ size = 32 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <defs>
        <radialGradient id="lunaGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#66F0FF" stopOpacity="0.8" />
          <stop offset="100%" stopColor="#00E5FF" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="20" cy="20" r="18" fill="url(#lunaGlow)" />
      <circle
        cx="20"
        cy="20"
        r="12"
        stroke="#00E5FF"
        strokeWidth="1.25"
        fill="none"
      />
      <path
        d="M20 8 A12 12 0 0 1 20 32"
        stroke="#66F0FF"
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
      />
      <circle cx="20" cy="20" r="2" fill="#E6ECF5" />
    </svg>
  );
}

export function LunaWordmark() {
  return (
    <div className="flex items-center gap-2.5">
      <LunaMark size={28} />
      <div className="flex items-baseline gap-1.5">
        <span className="font-display text-lg font-bold tracking-[0.2em] text-ice">
          LUNA
        </span>
        <span className="font-display text-[10px] tracking-[0.3em] text-cyan">
          CDSS
        </span>
      </div>
    </div>
  );
}
