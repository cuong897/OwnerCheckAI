import { useEffect, useRef, useState } from "react";
import { getToken } from "@/hooks/useAuth";

export interface RecognitionEvent {
  type: "recognition";
  log_id: number;
  camera_id: number;
  plate_text: string;
  conf_detect: number;
  timestamp: string;
  image_url: string | null;
  owner: {
    registered: boolean;
    owner_name?: string | null;
    vehicle_type?: string | null;
    brand?: string | null;
    color?: string | null;
  };
  watchlist: { category: "BLACKLIST" | "WHITELIST"; note: string | null } | null;
  alert: boolean;
}

/**
 * Track aggregate cho 1 biển số (gom các lần OCR ra plate gần giống nhau).
 *  - `plate_text` : reading có confidence cao nhất từ tất cả các lần thấy
 *  - `hits`       : số lần thấy plate "tương tự" (Levenshtein ≤ 2 hoặc cùng prefix dài)
 *  - `confirmed`  : true khi hits ≥ CONFIRM_THRESHOLD
 */
export interface PlateTrack {
  plate_text: string;
  best_conf: number;
  hits: number;
  first_seen: string;
  last_seen: string;
  confirmed: boolean;
  image_url: string | null;
  owner: RecognitionEvent["owner"];
  watchlist: RecognitionEvent["watchlist"];
  alert: boolean;
  log_id: number;
}

const HISTORY_SIZE = 8;
const CONFIRM_THRESHOLD = 2;          // ≥ N lần thấy → "confirmed"
const TRACK_TTL_MS = 15_000;          // xe rời khỏi khung sau ~15s → đóng track
const MIN_CONF_FOR_TRACK = 0.4;        // bỏ noise quá thấp

/**
 * Khoảng cách Levenshtein đơn giản (chỉ dùng cho chuỗi < 20 ký tự).
 * Trả về 0 nếu giống hệt, số nhỏ nếu khác ít.
 */
function levenshtein(a: string, b: string): number {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;
  const m = a.length, n = b.length;
  const dp: number[] = new Array(n + 1);
  for (let j = 0; j <= n; j++) dp[j] = j;
  for (let i = 1; i <= m; i++) {
    let prev = dp[0];
    dp[0] = i;
    for (let j = 1; j <= n; j++) {
      const tmp = dp[j];
      dp[j] = a[i - 1] === b[j - 1]
        ? prev
        : 1 + Math.min(prev, dp[j], dp[j - 1]);
      prev = tmp;
    }
  }
  return dp[n];
}

/** Bỏ ký tự ngăn cách để so sánh "core" giữa 2 reading khác format. */
function plateCore(s: string): string {
  return s.replace(/[^A-Z0-9]/gi, "").toUpperCase();
}

/**
 * Realtime stream + tracker: gom các lần đọc cùng 1 xe thành 1 track duy nhất,
 * vote confidence, đánh dấu confirmed sau N lần thấy.
 *
 *  - `tracks`    : danh sách plate track còn "sống" (chưa hết TTL), sort mới → cũ.
 *                  Mỗi xe = 1 entry duy nhất, không phải 1 entry / frame.
 *  - `connected` : trạng thái SSE
 */
export const useRecognitionSSE = (cameraId: number | null) => {
  const [tracks, setTracks] = useState<PlateTrack[]>([]);
  const [connected, setConnected] = useState(false);
  const seenLogIdsRef = useRef<Set<number>>(new Set());
  const tracksRef = useRef<PlateTrack[]>([]);

  useEffect(() => {
    if (!cameraId) {
      setTracks([]);
      setConnected(false);
      seenLogIdsRef.current.clear();
      tracksRef.current = [];
      return;
    }

    const token = getToken();
    if (!token) return;

    setTracks([]);
    seenLogIdsRef.current.clear();
    tracksRef.current = [];

    const url = `/events/recognitions?camera_id=${cameraId}&token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    // Periodic sweep: bỏ track đã hết TTL khỏi list. Nếu không thì
    // tracks cũ sẽ lưu mãi và làm UI loạn.
    const sweepInterval = window.setInterval(() => {
      const now = Date.now();
      const fresh = tracksRef.current.filter(
        (t) => now - new Date(t.last_seen).getTime() < TRACK_TTL_MS
      );
      if (fresh.length !== tracksRef.current.length) {
        tracksRef.current = fresh;
        setTracks([...fresh]);
      }
    }, 2000);

    es.addEventListener("recognition", (event: MessageEvent) => {
      try {
        const data: RecognitionEvent = JSON.parse(event.data);
        if (seenLogIdsRef.current.has(data.log_id)) return;
        seenLogIdsRef.current.add(data.log_id);
        // Cap seen set để không grow vô hạn trong session dài
        if (seenLogIdsRef.current.size > 2000) {
          const arr = Array.from(seenLogIdsRef.current);
          seenLogIdsRef.current = new Set(arr.slice(-1000));
        }

        if (!data.plate_text || data.conf_detect < MIN_CONF_FOR_TRACK) return;

        const plateCoreNew = plateCore(data.plate_text);
        const now = Date.now();

        // Tìm track tương tự trong list — Levenshtein ≤ 2 trên core, và chưa hết TTL
        const idx = tracksRef.current.findIndex((t) => {
          if (now - new Date(t.last_seen).getTime() > TRACK_TTL_MS) return false;
          return levenshtein(plateCore(t.plate_text), plateCoreNew) <= 2;
        });

        if (idx === -1) {
          // Track mới
          const newTrack: PlateTrack = {
            plate_text: data.plate_text,
            best_conf: data.conf_detect,
            hits: 1,
            first_seen: data.timestamp,
            last_seen: data.timestamp,
            confirmed: 1 >= CONFIRM_THRESHOLD,
            image_url: data.image_url,
            owner: data.owner,
            watchlist: data.watchlist,
            alert: data.alert,
            log_id: data.log_id,
          };
          tracksRef.current = [newTrack, ...tracksRef.current].slice(0, HISTORY_SIZE);
        } else {
          // Cập nhật track có sẵn — pick reading conf cao hơn làm canonical
          const existing = tracksRef.current[idx];
          const useNewReading = data.conf_detect > existing.best_conf;
          const updated: PlateTrack = {
            ...existing,
            plate_text: useNewReading ? data.plate_text : existing.plate_text,
            best_conf: useNewReading ? data.conf_detect : existing.best_conf,
            image_url: useNewReading ? data.image_url : existing.image_url,
            hits: existing.hits + 1,
            last_seen: data.timestamp,
            confirmed: existing.hits + 1 >= CONFIRM_THRESHOLD,
            // Giữ enrichment owner/watchlist mới nhất (có thể có)
            owner: data.owner.registered ? data.owner : existing.owner,
            watchlist: data.watchlist ?? existing.watchlist,
            alert: existing.alert || data.alert,
          };
          // Đưa track vừa cập nhật lên đầu list (mới nhất)
          const next = [updated, ...tracksRef.current.filter((_, i) => i !== idx)];
          tracksRef.current = next.slice(0, HISTORY_SIZE);
        }

        setTracks([...tracksRef.current]);
      } catch (err) {
        console.error("Recognition SSE parse error:", err);
      }
    });

    return () => {
      es.close();
      window.clearInterval(sweepInterval);
      setConnected(false);
    };
  }, [cameraId]);

  return { tracks, connected };
};
