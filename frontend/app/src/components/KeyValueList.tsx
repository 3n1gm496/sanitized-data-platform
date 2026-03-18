type KeyValueItem = {
  label: string;
  value: string;
};

type KeyValueListProps = {
  items: KeyValueItem[];
};

export function KeyValueList({ items }: KeyValueListProps) {
  return (
    <dl className="key-value-list">
      {items.map((item) => (
        <div key={item.label} className="key-value-list__row">
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
