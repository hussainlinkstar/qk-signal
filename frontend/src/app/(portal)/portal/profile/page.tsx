import PortalPreferences from "@/components/portal/PortalPreferences";

export default function PortalProfilePage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight text-(--foreground)">
        Notification Preferences
      </h1>
      <p className="text-sm text-(--muted-foreground)">
        Manage how and when you receive updates about your projects.
      </p>
      <PortalPreferences />
    </div>
  );
}
