/**
 * Formats dates received from the API for display only.
 *
 * The database/API keep ISO-like values (YYYY-MM-DD or YYYYMMDD) so dates
 * remain sortable and usable by date inputs. The UI always shows DD/MM/YYYY.
 */
export function formatDisplayDate(value: string | null | undefined): string | null {
  if (!value) return null;

  const compact = value.replaceAll("-", "");
  if (!/^\d{8}$/.test(compact)) return null;

  return `${compact.slice(6, 8)}/${compact.slice(4, 6)}/${compact.slice(0, 4)}`;
}
