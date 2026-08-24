import { useEffect, useState } from "react";
import * as api from "../api/client";

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
    return <div className="text-slate-400">No recent timesheets found.</div>;
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-slate-100">Recent Timecards</h2>
      <div className="overflow-x-auto rounded border border-slate-700">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-800 text-slate-300">
            <tr>
              <th className="p-3">Date</th>
              <th className="p-3">Project / Comment</th>
              <th className="p-3">Status</th>
              <th className="p-3 text-right">Hours</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 bg-slate-900/50">
            {items.map((item: TimecardItem, idx: number) => {
              const event = item.timeRecordEvent?.[0] || item;
              const attrs = event.timeRecordEventAttribute || [];
              const commentAttr = attrs.find((a: TimeAttribute) => a.attributeName === "Comment");
              const comment = commentAttr ? commentAttr.attributeValue : "N/A";
              
              // Basic date parse from start time
              let dateStr = "Unknown Date";
              if (event.startTime) {
                const dateObj = new Date(event.startTime);
                dateStr = dateObj.toLocaleDateString();
              }

              return (
                <tr key={idx}>
                  <td>{dateStr}</td>
                  <td>{comment}</td>
                  <td>
                    <span className={`badge ${event.eventStatus === 'APPROVED' ? 'success' : 'warning'}`}>
                      {event.eventStatus || 'Submitted'}
                    </span>
                  </td>
                  <td>{event.measure}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
