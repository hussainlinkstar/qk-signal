"use client";

import React from "react";

import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import SystemStatusClient from "./SystemStatusClient";

export default function AdminSystemStatusPage() {
  useAdminAccess();
  return <SystemStatusClient />;
}
