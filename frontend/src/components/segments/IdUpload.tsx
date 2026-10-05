import React, { useEffect, useId, useRef, useState } from 'react';
import { MembersAdded, MembersRemoved, SegmentsService } from '@/services/segments';
import {
  MAX_ID_LENGTH,
  MAX_SEGMENT_MEMBERS,
  ParsedIds,
  chunkIds,
  formatCount,
  parseIdFile,
} from '@/utils/segmentIds';
import { runChunks } from '@/utils/segmentUpload';
import { segmentErrorCopy } from '@/utils/segmentErrors';

export type UploadMode = 'add' | 'remove';

interface IdUploadProps {
  segmentId: string;
  segmentName: string;
  /** Members now, to refuse an add that would pass the cap before sending anything. */
  memberCount: number;
  mode: UploadMode;
  /** Called with the segment's member count after each accepted chunk. */
  onMemberCount: (count: number) => void;
  /** Told when an upload starts and ends, so the page can hold other controls still. */
  onRunningChange?: (running: boolean) => void;
  /** Wait between 429 retries; tests pass their own. */
  wait?: (seconds: number) => Promise<void>;
}

type Phase = 'choose' | 'summary' | 'confirm' | 'running' | 'failed' | 'stopped' | 'done';

interface Totals {
  sent: number;
  changed: number;
  unchanged: number;
  memberCount: number | null;
}

const ZERO: Totals = { sent: 0, changed: 0, unchanged: 0, memberCount: null };

/** How often the screen-reader status may speak during an upload, at most. */
const ANNOUNCE_EVERY_MS = 5000;

function realWait(seconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

function readFileText(file: File): Promise<string> {
  if (typeof file.text === 'function') return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

function lineList(lines: number[]): string {
  const shown = lines.slice(0, 5).map(String);
  const rest = lines.length - shown.length;
  const head = shown.length === 1 ? `line ${shown[0]}` : `lines ${shown.join(', ')}`;
  return rest > 0 ? `${head} and ${formatCount(rest)} more` : head;
}

const ids = (n: number) => `${formatCount(n)} ID${n === 1 ? '' : 's'}`;

/**
 * Add or remove a file of user ids on an id-list segment (#440): read and
 * summarised in the browser, then sent in chunks of at most 10,000 ids and
 * 1 MB, stopping at the first failure.
 */
export function IdUpload({
  segmentId,
  segmentName,
  memberCount,
  mode,
  onMemberCount,
  onRunningChange,
  wait = realWait,
}: IdUploadProps) {
  const inputId = useId();
  const helpId = useId();
  const [phase, setPhase] = useState<Phase>('choose');
  const [fileName, setFileName] = useState('');
  const [parsed, setParsed] = useState<ParsedIds | null>(null);
  const [fileProblem, setFileProblem] = useState<string | null>(null);
  const [chunks, setChunks] = useState<string[][]>([]);
  const [next, setNext] = useState(0);
  const [totals, setTotals] = useState<Totals>(ZERO);
  const [error, setError] = useState<string | null>(null);
  const [waiting, setWaiting] = useState<number | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const stopRef = useRef(false);
  const lastAnnounce = useRef(0);
  const outcomeRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const adding = mode === 'add';
  const verb = adding ? 'Add' : 'Remove';

  useEffect(() => {
    onRunningChange?.(phase === 'running');
  }, [phase, onRunningChange]);

  // Leaving mid-upload asks first; chunks already sent stay sent.
  useEffect(() => {
    if (phase !== 'running') return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [phase]);

  useEffect(() => {
    if (phase === 'failed' || phase === 'done' || phase === 'stopped') outcomeRef.current?.focus();
  }, [phase]);

  const reset = () => {
    setPhase('choose');
    setParsed(null);
    setFileName('');
    setFileProblem(null);
    setChunks([]);
    setNext(0);
    setTotals(ZERO);
    setError(null);
    setWaiting(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const handleFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setFileProblem(null);
    let text: string;
    try {
      text = await readFileText(file);
    } catch {
      setFileProblem('This file could not be read. Choose a CSV or text file.');
      return;
    }
    const result = parseIdFile(text);
    setFileName(file.name);
    if (result.ids.length === 0) {
      setParsed(null);
      setFileProblem('This file has no IDs.');
      return;
    }
    setParsed(result);
    setPhase('summary');
  };

  const room = MAX_SEGMENT_MEMBERS - memberCount;
  const overCap = adding && parsed !== null && parsed.ids.length > room;

  const run = async (all: string[][], startAt: number, before: Totals) => {
    stopRef.current = false;
    setPhase('running');
    setError(null);
    let running = before;
    const result = await runChunks({
      chunks: all,
      startAt,
      send: (batch): Promise<MembersAdded | MembersRemoved> =>
        adding ? SegmentsService.addMembers(segmentId, batch) : SegmentsService.removeMembers(segmentId, batch),
      onChunkDone: (index, res) => {
        const counts = res as Partial<MembersAdded> & Partial<MembersRemoved> & { member_count: number };
        running = {
          sent: running.sent + all[index].length,
          changed: running.changed + (adding ? counts.added ?? 0 : counts.removed ?? 0),
          unchanged: running.unchanged + (adding ? counts.already_members ?? 0 : counts.not_members ?? 0),
          memberCount: counts.member_count,
        };
        setTotals(running);
        setNext(index + 1);
        setWaiting(null);
        onMemberCount(counts.member_count);
        const now = Date.now();
        if (index === all.length - 1 || now - lastAnnounce.current >= ANNOUNCE_EVERY_MS) {
          lastAnnounce.current = now;
          setAnnouncement(`Uploaded chunk ${index + 1} of ${all.length}.`);
        }
      },
      shouldStop: () => stopRef.current,
      wait,
      onWait: (seconds) => setWaiting(seconds),
    });
    setWaiting(null);
    setNext(result.next);
    if (result.outcome === 'failed') {
      setError(segmentErrorCopy(result.error, 'members'));
      setPhase('failed');
    } else {
      setPhase(result.outcome);
    }
  };

  const start = () => {
    if (!parsed || overCap) return;
    const all = chunkIds(parsed.ids, adding ? 'add' : 'remove');
    setChunks(all);
    setTotals(ZERO);
    void run(all, 0, ZERO);
  };

  const total = parsed?.ids.length ?? 0;
  const progressText = `Uploaded chunk ${next} of ${chunks.length} (${formatCount(totals.sent)} of ${ids(total)})`;
  const sentBefore = adding
    ? `${ids(totals.changed)} ${totals.changed === 1 ? 'was' : 'were'} added before it stopped.`
    : `${ids(totals.changed)} ${totals.changed === 1 ? 'was' : 'were'} removed before it stopped.`;
  const safeAgain = adding
    ? 'Adding the same IDs again is safe: IDs already in the segment are skipped.'
    : 'Removing the same IDs again is safe: IDs not in the segment are skipped.';

  return (
    <div className="space-y-3" data-testid={`upload-${mode}`}>
      {(phase === 'choose' || phase === 'summary') && (
        <div>
          <label htmlFor={inputId} className="block text-sm font-medium text-slate-800">
            {adding ? 'Upload a CSV or text file of user IDs' : 'Upload a CSV or text file of user IDs to remove'}
          </label>
          <p id={helpId} className="mt-1 text-xs text-slate-600">
            One ID per line, in the first column. A first row reading <code>user_id</code> is treated as a header.
            IDs are matched exactly, including case and spaces. Up to 1,000,000 IDs per segment; each ID up to{' '}
            {MAX_ID_LENGTH} characters.
          </p>
          <input
            ref={inputRef}
            id={inputId}
            type="file"
            accept=".csv,.txt,text/csv,text/plain"
            aria-describedby={helpId}
            onChange={(e) => void handleFile(e)}
            className="mt-2 block text-sm"
            data-testid={`upload-file-${mode}`}
          />
          {fileProblem && (
            <p role="alert" className="mt-2 text-sm text-red-700" data-testid="upload-file-problem">
              {fileProblem}
            </p>
          )}
        </div>
      )}

      {phase === 'summary' && parsed && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm" data-testid="upload-summary">
          <p>
            <strong>
              {ids(parsed.ids.length)} found in {fileName}.
            </strong>{' '}
            {parsed.duplicates > 0 && `${formatCount(parsed.duplicates)} duplicate${parsed.duplicates === 1 ? '' : 's'} removed. `}
            {parsed.tooLong.length > 0 &&
              `${formatCount(parsed.tooLong.length)} row${parsed.tooLong.length === 1 ? '' : 's'} skipped: ${lineList(parsed.tooLong)} ${
                parsed.tooLong.length === 1 ? 'is' : 'are'
              } longer than ${MAX_ID_LENGTH} characters.`}
          </p>
          {overCap ? (
            <p role="alert" className="mt-2 text-red-700" data-testid="upload-over-cap">
              This segment can hold 1,000,000 IDs. It has {formatCount(memberCount)}, so at most {formatCount(Math.max(room, 0))} more
              can be added; this file has {formatCount(parsed.ids.length)}. Split the file or remove IDs first.
            </p>
          ) : (
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={() => (adding ? start() : setPhase('confirm'))}
                className="px-3 py-1.5 rounded-md text-sm font-medium bg-blue-600 text-white hover:bg-blue-700"
                data-testid="upload-start"
              >
                {verb} {ids(parsed.ids.length)}
              </button>
              <button
                type="button"
                onClick={reset}
                className="px-3 py-1.5 rounded-md text-sm font-medium border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                data-testid="upload-choose-again"
              >
                Choose a different file
              </button>
            </div>
          )}
        </div>
      )}

      {phase === 'confirm' && parsed && (
        <div
          role="group"
          aria-labelledby={`${helpId}-confirm`}
          className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm"
          data-testid="upload-confirm"
        >
          <p id={`${helpId}-confirm`} className="text-amber-900">
            Remove {ids(parsed.ids.length)} from {segmentName}? Flags and experiments that target this segment will stop
            matching these users. Existing experiment assignments are kept.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              autoFocus
              onClick={() => setPhase('summary')}
              className="px-3 py-1.5 rounded-md text-sm font-medium border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
              data-testid="upload-confirm-cancel"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={start}
              className="px-3 py-1.5 rounded-md text-sm font-medium bg-red-700 text-white hover:bg-red-800"
              data-testid="upload-confirm-yes"
            >
              Remove {ids(parsed.ids.length)}
            </button>
          </div>
        </div>
      )}

      {phase === 'running' && (
        <div className="space-y-2" data-testid="upload-running">
          <progress
            aria-label="Upload progress"
            value={next}
            max={chunks.length}
            className="w-full"
            data-testid="upload-progress"
          />
          <p className="text-sm text-slate-700" data-testid="upload-progress-text">
            {progressText}
          </p>
          {waiting !== null && (
            <p className="text-sm text-amber-900" data-testid="upload-waiting">
              The server asked us to wait. Continuing in {waiting} second{waiting === 1 ? '' : 's'}...
            </p>
          )}
          <button
            type="button"
            onClick={() => {
              stopRef.current = true;
            }}
            className="px-3 py-1.5 rounded-md text-sm font-medium border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
            data-testid="upload-stop"
          >
            Stop upload
          </button>
          <p className="text-xs text-slate-600">Stops after the current chunk. IDs already sent stay as they are.</p>
        </div>
      )}

      <div role="status" aria-live="polite" className="sr-only" data-testid="upload-announcer">
        {announcement}
      </div>

      {phase === 'failed' && (
        <div
          ref={outcomeRef}
          tabIndex={-1}
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"
          data-testid="upload-failed"
        >
          <p>
            Upload stopped at chunk {next + 1} of {chunks.length}: {error} {sentBefore} {safeAgain}
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => void run(chunks, next, totals)}
              className="px-3 py-1.5 rounded-md text-sm font-medium bg-white border border-red-200 hover:bg-red-100"
              data-testid="upload-retry"
            >
              Retry from chunk {next + 1}
            </button>
            <button
              type="button"
              onClick={reset}
              className="px-3 py-1.5 rounded-md text-sm font-medium bg-white border border-red-200 hover:bg-red-100"
              data-testid="upload-dismiss"
            >
              Done
            </button>
          </div>
        </div>
      )}

      {phase === 'stopped' && (
        <div
          ref={outcomeRef}
          tabIndex={-1}
          className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm"
          data-testid="upload-stopped"
        >
          <p>
            Upload stopped after chunk {next} of {chunks.length}. {sentBefore} {safeAgain}
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => void run(chunks, next, totals)}
              className="px-3 py-1.5 rounded-md text-sm font-medium bg-white border border-slate-300 hover:bg-slate-100"
              data-testid="upload-continue"
            >
              Continue from chunk {next + 1}
            </button>
            <button
              type="button"
              onClick={reset}
              className="px-3 py-1.5 rounded-md text-sm font-medium bg-white border border-slate-300 hover:bg-slate-100"
              data-testid="upload-dismiss"
            >
              Done
            </button>
          </div>
        </div>
      )}

      {phase === 'done' && (
        <div
          ref={outcomeRef}
          tabIndex={-1}
          className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-900"
          data-testid="upload-done"
        >
          <p>
            {adding
              ? `${ids(totals.sent)} uploaded. ${formatCount(totals.changed)} ${totals.changed === 1 ? 'was' : 'were'} added and ${formatCount(
                  totals.unchanged,
                )} ${totals.unchanged === 1 ? 'was already a member' : 'were already members'}.`
              : `${ids(totals.sent)} sent. ${formatCount(totals.changed)} ${totals.changed === 1 ? 'was' : 'were'} removed and ${formatCount(
                  totals.unchanged,
                )} ${totals.unchanged === 1 ? 'was not a member' : 'were not members'}.`}{' '}
            The segment now has {formatCount(totals.memberCount ?? 0)} member{totals.memberCount === 1 ? '' : 's'}.
          </p>
          <button
            type="button"
            onClick={reset}
            className="mt-3 px-3 py-1.5 rounded-md text-sm font-medium bg-white border border-green-200 hover:bg-green-100"
            data-testid="upload-dismiss"
          >
            Done
          </button>
        </div>
      )}
    </div>
  );
}
