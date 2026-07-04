import logoUrl from '../../../build/icon.png';

export function Logo({ size = 42, className = '' }: { size?: number; className?: string }) {
  return <img className={className} src={logoUrl} width={size} height={size} alt="Local Agent Studio" />;
}
