import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import * as api from '../../api/client';
import { formatDateInAppTimezone } from '../../lib/entries';
interface TimeAttribute {
  attributeName: string;
  attributeValue: string;
}
interface TimeStatus {
  displayValue?: string;
  statusCode?: string;
}
interface TimeRecordEvent {
  startTime?: string;
  timeRecordEventAttribute?: TimeAttribute[];
  eventStatus?: string;
  measure?: number | string;
}
interface TimecardItem {
  timeRecordEvent?: TimeRecordEvent[];
  timeRecordEventAttribute?: TimeAttribute[];
  timeStatuses?: TimeStatus[];
  startTime?: string;
  eventStatus?: string;
  measure?: number | string;
}
interface TimecardsResponse {
  items: TimecardItem[];
}
export default function TimecardHistory({
  onSessionExpired,
}: {
  onSessionExpired: () => void;
}) {
  const [data, setData] = useState<TimecardsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    api
      .listTimecards(25, 0, controller.signal)
      .then((res) => {
        if (controller.signal.aborted) return;
        setData({
          items: Array.isArray(res.items) ? (res.items as TimecardItem[]) : [],
        });
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof api.ApiError && err.status === 401) {
          onSessionExpired();
          return;
        }
        setError(
          err instanceof Error && err.message
            ? err.message
            : 'Failed to load timesheets'
        );
        setLoading(false);
      });
    return () => controller.abort();
  }, [onSessionExpired]);
  if (loading) {
    return (
      <div className="card loading">
        Loading timesheets from Oracle Fusion...
      </div>
    );
  }
  if (error) {
    return <div className="card error">{error}</div>;
  }
  const items = data?.items || [];
  if (items.length === 0) {
    return <div className="text-muted">No recent timesheets found.</div>;
  }
  return (
    <div className="timecard-history">
      <h2 className="timecard-title">Recent Timecards</h2>
      <div className="table-wrap">
        <table className="timecard-table">
          <thead className="timecard-header">
            <tr>
              <th className="timecard-cell">Date</th>
              <th className="timecard-cell">Project / Comment</th>
              <th className="timecard-cell">Status</th>
              <th className="timecard-cell timecard-cell-num">Hours</th>
            </tr>
          </thead>
          <tbody className="timecard-body">
             {items.map((item: TimecardItem, idx: number) => {
               const event = item.timeRecordEvent?.[0];
               const attrs =
                 event?.timeRecordEventAttribute || item.timeRecordEventAttribute || [];
               const commentAttr = attrs.find(
                 (a: TimeAttribute) => a.attributeName === 'Comment'
               );
               const comment = commentAttr ? commentAttr.attributeValue : 'N/A';
               const startTime = event?.startTime || item.startTime;
               let dateStr = 'Unknown Date';
               if (startTime) {
                 const dateObj = new Date(startTime);
                 if (!isNaN(dateObj.getTime())) {
                    dateStr = formatDateInAppTimezone(dateObj);
                 }
               }
               const statusValue =
                 event?.eventStatus ||
                 item.eventStatus ||
                 item.timeStatuses?.[0]?.displayValue ||
                 item.timeStatuses?.[0]?.statusCode ||
                 'Unknown';
               const status = String(statusValue);
               const isApproved = status.toUpperCase() === 'APPROVED';
               const measure = event?.measure ?? item.measure ?? '—';
               return (
                 <motion.tr
                   key={idx}
                   className="timecard-row"
                   initial={{ opacity: 0, y: 10 }}
                   animate={{ opacity: 1, y: 0 }}
                   transition={{ duration: 0.3, delay: idx * 0.05 }}
                 >
                   <td className="timecard-cell">{dateStr}</td>
                   <td className="timecard-cell">{comment}</td>
                   <td className="timecard-cell">
                     <span
                       className={`badge ${isApproved ? 'badge-success' : 'badge-warning'}`}
                     >
                       {status}
                     </span>
                   </td>
                   <td className="timecard-cell timecard-cell-num">
                     {measure}
                   </td>
                 </motion.tr>
               );
             })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
