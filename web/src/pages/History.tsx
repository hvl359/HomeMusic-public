import { useEffect, useState } from 'react';
import { errorMessage, request } from '../api/client';
import { Button, ErrorState, Loading, PageHeader } from '../components/ui';
import { listen } from '../lib/listen';

interface Entry {
  id: number;
  ts: string;
  kind: string;
  client: string;
  ref: string | null;
  nd_song_id: string | null;
  title: string | null;
  artist: string | null;
  duration_s: number | null;
  listened_ms: number | null;
}
interface History { items: Entry[]; next_offset: number | null }
const status: Record<string, string> = {
  start: 'Начато', progress: 'Воспроизведение', skip: 'Пропущено', finish: 'Завершено',
  interrupted: 'Прервано', error: 'Ошибка воспроизведения',
};

export function HistoryPage() {
  const [items, setItems] = useState<Entry[]>([]);
  const [next, setNext] = useState<number | null>(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const load = async (offset: number, signal?: AbortSignal) => {
    setBusy(true);
    setError(undefined);
    try {
      const data = await request<History>('GET', `/api/plays/history?offset=${offset}`, { signal });
      if (signal?.aborted) return;
      setItems(old => offset === 0 ? data.items : [...old, ...data.items.filter(x => !old.some(y => y.id === x.id))]);
      setNext(data.next_offset);
    } catch (e) {
      if (!signal?.aborted) setError(errorMessage(e));
    } finally {
      if (!signal?.aborted) setBusy(false);
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    void load(0, controller.signal);
    return () => controller.abort();
  }, []);
  return <div>
    <PageHeader title="История прослушивания" back="/more" />
    <div className="px-4 space-y-4">
      <p className="text-sm text-muted">Только ваша история. Повторные запуски показаны отдельно; начало трека не означает полное прослушивание.</p>
      <Button disabled={busy} onClick={() => void load(0)}>Обновить</Button>
      {error && <ErrorState text={error} onRetry={() => void load(next ?? 0)} />}
      {!busy && !error && !items.length && <p>История пока пуста. Она появится после воспроизведения треков.</p>}
      <ul className="divide-y divide-line">
        {items.map(item => {
          const ref = item.nd_song_id ? `nd:${item.nd_song_id}` : item.ref;
          return <li key={item.id} className="py-3">
            <button type="button" disabled={!ref} className="w-full text-left disabled:opacity-50"
              aria-label={`Слушать: ${item.title ?? 'Неизвестный трек'}`}
              onClick={() => ref && listen({ ref, nd_song_id: item.nd_song_id, title: item.title ?? 'Неизвестный трек',
                artist: item.artist ?? 'Неизвестный исполнитель', duration_s: item.duration_s })}>
              <span className="block font-semibold">{item.title ?? 'Неизвестный трек'}</span>
              <span className="block text-sm text-muted">{item.artist ?? 'Неизвестный исполнитель'}</span>
            </button>
            <div className="text-xs text-muted mt-1">
              <time dateTime={item.ts}>{new Date(item.ts).toLocaleString()}</time> · {item.client === 'navidrome' ? 'Засчитано Navidrome' : status[item.kind] ?? item.kind}
              {item.listened_ms != null && ` · слушали ${Math.floor(item.listened_ms / 1000)} с`}
            </div>
          </li>;
        })}
      </ul>
      {busy && <Loading />}
      {next !== null && items.length > 0 && <Button disabled={busy} onClick={() => void load(next)}>Загрузить ещё</Button>}
    </div>
  </div>;
}
