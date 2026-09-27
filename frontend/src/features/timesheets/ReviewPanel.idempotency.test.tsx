import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ReviewPanel from './ReviewPanel';
import type { SubmitResultCode, TimecardEntry } from '../../types';

/**
 * These tests drive the real `api.submitTimecard` through `fetch`. The fake
 * server below is a port of `backend/services/idempotency.py`,
 * `backend/services/otl_client.py`, and `backend/api/v1/timecards.py`:
 *
 * - `request_fingerprint` excludes employeeName, so a name-only correction is
 *   not material and the same key replays instead of writing a second timecard;
 * - only a *definitive* result is memoised. An ambiguous one (5xx, unavailable
 *   store) releases the claim, so re-sending the same requestId really does get
 *   another attempt at Oracle instead of the identical failure for 24 hours;
 * - `POST /api/otl/timecard` answers 502 when nothing succeeded and any failure
 *   is retryable, else 422, with the per-row body either way.
 *
 * Re-mocking the API function would prove nothing about any of that.
 */

interface FakeRow {
  index: number;
  ok: boolean;
  id?: string;
  recordNumber?: string;
  recordName?: string;
  status?: number;
  error?: string;
  requestId?: string;
  replayed?: boolean;
  code?: SubmitResultCode;
}

type OracleOutcome =
  { ok: true } | { ok: false; status: number; code?: SubmitResultCode };

const CODE_ORACLE_UNAVAILABLE: SubmitResultCode = 'oracle_unavailable';
const CODE_REQUEST_ID_CONFLICT: SubmitResultCode = 'request_id_conflict';

const FAILURE_TEXT: Record<number, string> = {
  400: 'Oracle rejected this timecard entry.',
  409: 'The timecard request conflicts with an existing request.',
  500: 'Oracle Cloud is temporarily unavailable.',
  503: 'Oracle Cloud is temporarily unavailable.',
};

const RETRYABLE_CODES: readonly SubmitResultCode[] = [
  'submission_in_progress',
  'idempotency_claim_lost',
  'idempotency_unavailable',
  'oracle_unavailable',
];

/** Mirrors `services/idempotency.py::is_retryable_result`. */
function isRetryable(row: FakeRow): boolean {
  if (row.ok) return false;
  if (row.code && RETRYABLE_CODES.includes(row.code)) return true;
  if (row.code === CODE_REQUEST_ID_CONFLICT) return false;
  const status = row.status ?? 500;
  return status >= 500 || status === 409 || status === 429;
}

/** Mirrors `_is_ambiguous_result`: only an ambiguous outcome loses its record. */
function isAmbiguous(row: FakeRow): boolean {
  if (row.ok) return false;
  if (
    row.code === 'idempotency_unavailable' ||
    row.code === CODE_ORACLE_UNAVAILABLE
  ) {
    return true;
  }
  return (row.status ?? 500) >= 500;
}

/** Mirrors `scoped_idempotency_key` — per employee, per request key. */
function scopedKey(employeeNumber: string, requestId: string): string {
  return `timecard:${employeeNumber}:${requestId}`;
}

/**
 * Mirrors `request_fingerprint`: every field is material for conflict detection
 * *except* employeeName and the key fields themselves.
 */
function requestFingerprint(entry: Record<string, unknown>): string {
  const payload: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(entry)) {
    if (
      key === 'requestId' ||
      key === 'idempotencyKey' ||
      key === 'Idempotency-Key'
    ) {
      continue;
    }
    if (key.toLowerCase().includes('employeename')) continue;
    payload[key] = value;
  }
  return JSON.stringify(
    Object.keys(payload)
      .sort()
      .map((key) => [key, payload[key]])
  );
}

class FakeOtlServer {
  /** Every entry that actually reached Oracle, successful or not. */
  oracleAttempts: TimecardEntry[] = [];
  /** Oracle record numbers that were really created. */
  createdRecords: string[] = [];
  /** Request keys the client sent, in order. */
  seenKeys: string[] = [];
  /** Consumed front to back; an empty queue means "succeed". */
  outcomes: OracleOutcome[] = [];
  /** Requests to fully process and then fail at the transport layer. */
  dropResponses = 0;
  private store = new Map<string, { fingerprint: string; result: FakeRow }>();
  private created = 0;

  async handle(entries: TimecardEntry[]): Promise<Response> {
    const results: FakeRow[] = [];
    for (const [index, entry] of entries.entries()) {
      const requestId = String(entry.requestId);
      const key = scopedKey(String(entry.employeeNumber), requestId);
      this.seenKeys.push(requestId);
      const fingerprint = requestFingerprint(
        entry as unknown as Record<string, unknown>
      );
      const record = this.store.get(key);

      if (record && record.fingerprint !== fingerprint) {
        results.push({
          index,
          ok: false,
          status: 409,
          code: CODE_REQUEST_ID_CONFLICT,
          error: 'This requestId was already used for different timecard data.',
          requestId,
        });
        continue;
      }
      if (record) {
        results.push({ ...record.result, index, replayed: true });
        continue;
      }

      this.oracleAttempts.push({ ...entry });
      const outcome = this.outcomes.shift() ?? { ok: true as const };
      let row: FakeRow;
      if (outcome.ok) {
        this.created += 1;
        const recordNumber = `REC-${this.created}`;
        this.createdRecords.push(recordNumber);
        row = {
          index,
          ok: true,
          id: recordNumber,
          recordNumber,
          recordName: '2026-09-25',
          requestId,
        };
      } else {
        row = {
          index,
          ok: false,
          status: outcome.status,
          code:
            outcome.code ??
            (outcome.status >= 500 ? CODE_ORACLE_UNAVAILABLE : undefined),
          error: FAILURE_TEXT[outcome.status] ?? 'Timecard submission failed.',
          requestId,
        };
      }
      if (!isAmbiguous(row)) {
        // A definitive outcome is stored and replayed for the whole TTL.
        this.store.set(key, { fingerprint, result: row });
      }
      results.push(row);
    }

    if (this.dropResponses > 0) {
      this.dropResponses -= 1;
      throw new TypeError('Failed to fetch');
    }

    const succeeded = results.filter((row) => row.ok).length;
    const failed = results.length - succeeded;
    return new Response(
      JSON.stringify({
        submitted: results.length,
        succeeded,
        failed,
        results,
        correlationId: 'test-correlation',
      }),
      {
        status:
          succeeded === 0 && failed === 0
            ? 200
            : succeeded === 0 && results.some(isRetryable)
              ? 502
              : succeeded === 0
                ? 422
                : 200,
        headers: { 'Content-Type': 'application/json' },
      }
    );
  }
}

function installServer(server: FakeOtlServer): void {
  const fetchMock = vi.fn(
    async (url: string | URL | Request, init?: RequestInit) => {
      const path = String(typeof url === 'string' ? url : String(url));
      if (path.startsWith('/api/otl/timecard')) {
        const body = JSON.parse(String(init?.body)) as {
          entries: TimecardEntry[];
        };
        return server.handle(body.entries);
      }
      return new Response(JSON.stringify({ detail: 'Not mocked' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      });
    }
  );
  vi.stubGlobal('fetch', fetchMock);
}

function makeEntry(overrides: Partial<TimecardEntry> = {}): TimecardEntry {
  return {
    requestId: 'request-1',
    employeeNumber: '7',
    employeeName: 'Mala Kumari',
    projectNo: 'PA-1',
    projectName: 'Operations',
    workOrder: 'WO-9',
    taskDetails: 'Reviewed weekly payroll entries',
    hours: 2.5,
    date: '2026-09-25',
    payrollTimeType: 'Regular',
    expenditureType: 'Regular Time',
    currencyCode: 'USD',
    ...overrides,
  };
}

describe('ReviewPanel against a real idempotency store', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('retries an unavailable Oracle under the same request key', async () => {
    // The server releases an ambiguous claim, so this is the documented and safe
    // retry. Rotating the key here would risk a duplicate timecard.
    const server = new FakeOtlServer();
    server.outcomes = [{ ok: false, status: 500 }];
    installServer(server);

    render(
      <ReviewPanel entries={[makeEntry()]} manual onSessionExpired={vi.fn()} />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));

    // The whole submission failed, and the client still gets a per-row answer.
    expect(await screen.findByText('Not Fully Confirmed')).toBeInTheDocument();
    expect(server.oracleAttempts).toHaveLength(1);
    expect(server.createdRecords).toHaveLength(0);
    expect(
      screen.getByText(
        /retrying the same request key gives oracle another attempt/i
      )
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Retry entry 1 with the same key',
      })
    );

    await waitFor(() =>
      expect(
        screen.getByText(/server confirmed 1 of 1 timecards/i)
      ).toBeInTheDocument()
    );
    // A second Oracle attempt, and no new key.
    expect(server.oracleAttempts).toHaveLength(2);
    expect(server.seenKeys).toEqual(['request-1', 'request-1']);
  });

  it('does not dead-end a row whose result the server has stored', async () => {
    // A definitive refusal is memoised for the full TTL, so the same key can
    // only ever replay it. This is the case that used to be unrecoverable.
    const server = new FakeOtlServer();
    server.outcomes = [{ ok: false, status: 400 }];
    installServer(server);
    const entry = makeEntry();

    render(<ReviewPanel entries={[entry]} manual onSessionExpired={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));

    expect(await screen.findByText('Not Fully Confirmed')).toBeInTheDocument();
    expect(server.oracleAttempts).toHaveLength(1);
    expect(server.createdRecords).toHaveLength(0);

    // The row the server refused must still be the user's to fix.
    expect(screen.getByLabelText('Hours')).toBeEnabled();
    expect(
      screen.getByRole('button', { name: 'Clear entry 1' })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/keeps this request key’s result for 24 hours/i)
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Submit entry 1 with a new key' })
    ).toBeInTheDocument();

    // A stored result is never offered as a same-key retry, because that would
    // only replay it. The escape hatch is explicit.
    expect(
      screen.queryByRole('button', { name: /with the same key/i })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', {
        name: /Retry 1 entry with the same request key/i,
      })
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', { name: 'Submit entry 1 with a new key' })
    );
    expect(screen.getByText(/creates a second timecard/i)).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', {
        name: /Issue a new request key and submit/,
      })
    );

    await waitFor(() =>
      expect(
        screen.getByText(/server confirmed 1 of 1 timecards/i)
      ).toBeInTheDocument()
    );
    // A second Oracle write only happened because a human asked for a new key.
    expect(server.oracleAttempts).toHaveLength(2);
    expect(server.createdRecords).toEqual(['REC-1']);
    expect(server.seenKeys).toHaveLength(2);
    expect(server.seenKeys[1]).not.toBe(server.seenKeys[0]);
  });

  it('does not create a second timecard when a lost response is followed by an edit', async () => {
    const server = new FakeOtlServer();
    server.dropResponses = 1;
    installServer(server);

    render(
      <ReviewPanel
        entries={[
          makeEntry(),
          makeEntry({
            requestId: 'request-2',
            taskDetails: 'Second task',
          }),
        ]}
        manual
        onSessionExpired={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));
    expect(await screen.findByText('Failed to fetch')).toBeInTheDocument();
    // Both rows were written before the response was lost.
    expect(server.createdRecords).toHaveLength(2);

    // The user corrects hours on the first entry and retries.
    fireEvent.change(screen.getAllByLabelText('Hours')[0], {
      target: { value: '3' },
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Retry submission safely' })
    );

    await waitFor(() =>
      expect(
        screen.getByText(/server confirmed 1 of 2 timecards/i)
      ).toBeInTheDocument()
    );
    // The unchanged row replayed its stored success; the edited row conflicted
    // on its stored fingerprint. Neither reached Oracle again.
    expect(server.oracleAttempts).toHaveLength(2);
    expect(server.createdRecords).toEqual(['REC-1', 'REC-2']);
    expect(server.seenKeys).toEqual([
      'request-1',
      'request-2',
      'request-1',
      'request-2',
    ]);
    expect(
      screen.getByText(/already used with different data/i)
    ).toBeInTheDocument();
    expect(screen.getByText('(replayed)')).toBeInTheDocument();

    // The conflict is loud, and the way out is an explicit new key.
    fireEvent.click(
      screen.getByRole('button', { name: 'Submit entry 1 with a new key' })
    );
    fireEvent.click(
      screen.getByRole('button', {
        name: /Issue a new request key and submit/,
      })
    );

    await waitFor(() =>
      expect(
        screen.getByText(/server confirmed 2 of 2 timecards/i)
      ).toBeInTheDocument()
    );
    expect(server.createdRecords).toEqual(['REC-1', 'REC-2', 'REC-3']);
  });

  it('replays rather than duplicates when only the employee name is corrected', async () => {
    const server = new FakeOtlServer();
    server.dropResponses = 1;
    installServer(server);

    render(
      <ReviewPanel entries={[makeEntry()]} manual onSessionExpired={vi.fn()} />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));
    expect(await screen.findByText('Failed to fetch')).toBeInTheDocument();
    expect(server.createdRecords).toHaveLength(1);

    // employeeName is deliberately excluded from the server's fingerprint, so
    // this correction is not material and the same key must still replay.
    fireEvent.change(screen.getByLabelText('Employee name'), {
      target: { value: 'Mala Kumari-Bhattacharya' },
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Retry submission safely' })
    );

    expect(
      await screen.findByText(/server confirmed 1 of 1 timecards/i)
    ).toBeInTheDocument();
    expect(server.createdRecords).toEqual(['REC-1']);
    expect(server.oracleAttempts).toHaveLength(1);
    expect(server.seenKeys).toEqual(['request-1', 'request-1']);
  });
});
