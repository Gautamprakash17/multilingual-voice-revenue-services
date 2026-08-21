type Props = {
  label: string;
  value: string;
  tone: "ok" | "warn" | "bad";
};

export default function StatusBadge({ label, value, tone }: Props) {
  return (
    <div className={`status-badge ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
