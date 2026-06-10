import { useEffect, useState } from "react";
import { fetchDevices, revokeDevice, type Device } from "./api";

export default function Devices() {
  const [devices, setDevices] = useState<Device[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchDevices().then((list) => {
      if (!cancelled) setDevices(list);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function revoke(id: string) {
    if (!confirm("Sign this device out? Its tokens stop working immediately.")) return;
    await revokeDevice(id);
    setDevices(await fetchDevices());
  }

  return (
    <div className="devices">
      <h2>Connected devices</h2>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Added</th>
            <th>Last seen</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {devices.map((device) => (
            <tr key={device.id} className={device.revoked ? "revoked" : ""}>
              <td>{device.name}</td>
              <td>{new Date(device.created_at).toLocaleDateString()}</td>
              <td>
                {device.last_seen_at
                  ? new Date(device.last_seen_at).toLocaleString()
                  : "—"}
              </td>
              <td>
                {device.revoked ? (
                  <span className="muted">revoked</span>
                ) : (
                  <button onClick={() => revoke(device.id)}>Revoke</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
