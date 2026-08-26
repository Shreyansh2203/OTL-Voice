import { useEffect, useState } from "react";
import * as api from "../../api/client";
interface TimeAttribute {
  attributeName: string;
  attributeValue: string;
}
interface TimeRecordEvent {
  startTime?: string;
  timeRecordEventAttribute?: TimeAttribute[];
  eventStatus?: string;
  measure?: number;
}
interface TimecardItem {
  timeRecordEvent?: TimeRecordEvent[];
  timeRecordEventAttribute?: TimeAttribute[];
  startTime?: string;
  eventStatus?: string;
  measure?: number;
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
    let mounted = true;
    api
      .listTimecards()
      .then((res) => {
        if (mounted) {
          setData(res as TimecardsResponse);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!mounted) return;
        if (err.status === 401) {
            onSessionExpired();
            return;
        }
        setError(err.message || "Failed to load timesheets");
        setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [onSessionExpired]);
  if (loading) {
    return <div className="card loading">Loading timesheets from Oracle Fusion...</div>;
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
              const event = item.timeRecordEvent?.[0] || item;
              const attrs = event.timeRecordEventAttribute || [];
              const commentAttr = attrs.find((a: TimeAttribute) => a.attributeName === "Comment");
              const comment = commentAttr ? commentAttr.attributeValue : "N/A";
// Basic date parse from start time
               let dateStr = "Unknown Date";
               if (event.startTime) {
                 const dateObj = new Date(event.startTime);
                 if (!isNaN(dateObj.getTime())) {
                   dateStr = dateObj.toLocaleDateString();
                 }
               }
              const status = event.eventStatus || 'Submitted';
              const isApproved = status === 'APPROVED';
              return (
                <tr key={idx} className="timecard-row">
                  <td className="timecard-cell">{dateStr}</td>
                  <td className="timecard-cell">{comment}</td>
                  <td className="timecard-cell">
                    <span className={`badge ${isApproved ? "badge-success" : "badge-warning"}`}>
                      {status}
                    </span>
                  </td>
                  <td className="timecard-cell timecard-cell-num">{event.measure}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}