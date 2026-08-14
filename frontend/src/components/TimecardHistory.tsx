import { useEffect, useState } from "react";
import * as api from "../api/client";

export default function TimecardHistory({
  onSessionExpired,
}: {
  onSessionExpired: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    let active = true;
    api
      .listTimecards(50, 0)
      .then((res) => {
        if (!active) return;
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof api.ApiError && err.status === 401) {
          onSessionExpired();
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load timesheets");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [onSessionExpired]);

  if (loading) {
    return <div className="card loading">Loading timesheets from Oracle Fusion...</div>;
  }

  if (error) {
    return <div className="card error">{error}</div>;
  }

  const items = data?.items || [];

  return (
    <div className="card history-panel">
      <h3>Submitted Timesheets (Fusion OTL)</h3>
      {items.length === 0 ? (
        <p className="muted">No recent timesheets found.</p>
      ) : (
        <table className="timecard-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Project</th>
              <th>Status</th>
              <th>Hours</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item: any, idx: number) => {
              const attrs = item.timeRecordEventAttribute || [];
              const commentAttr = attrs.find((a: any) => a.attributeName === "Comment");
              const comment = commentAttr ? commentAttr.attributeValue : "N/A";
              
              // Basic date parse from start time
              let dateStr = "Unknown Date";
              if (item.startTime) {
                const dateObj = new Date(item.startTime);
                dateStr = dateObj.toLocaleDateString();
              }

              return (
                <tr key={idx}>
                  <td>{dateStr}</td>
                  <td>{comment}</td>
                  <td>
                    <span className="badge success">Submitted</span>
                  </td>
                  <td>{item.measure}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
