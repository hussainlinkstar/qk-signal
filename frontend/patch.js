/* eslint-disable @typescript-eslint/no-var-requires */
const fs = require("fs");
const path = require("path");

const filePath = path.join(process.cwd(), "src/components/results/AuditWorkspace.tsx");
let content = fs.readFileSync(filePath, "utf-8");

// Use regex replacements to handle any CRLF/LF differences
content = content.replace(
  /import CommandPalette from "@\/components\/ui\/CommandPalette";\s*import FeatureLockOverlay from "@\/components\/dashboard\/FeatureLockOverlay";/,
  'import CommandPalette from "@/components/ui/CommandPalette";\nimport FeatureLockOverlay from "@/components/dashboard/FeatureLockOverlay";\nimport InsufficientCreditsModal from "@/components/billing/InsufficientCreditsModal";\nimport CreditTopUpModal from "@/components/billing/CreditTopUpModal";'
);

content = content.replace(
  /const \[copyStatus, setCopyStatus\] = useState\(""\);\s*const \[isExporting, setIsExporting\] = useState\(false\);\s*const scannerRef = React\.useRef<\{ triggerAiScan: \(\) => void \}>\(\w*null\w*\);\s*const \[isFormVisible, setIsFormVisible\] = useState\(true\);/,
  'const [copyStatus, setCopyStatus] = useState("");\n  const [isExporting, setIsExporting] = useState(false);\n  const scannerRef = React.useRef<{ triggerAiScan: () => void }>(null);\n  const [isFormVisible, setIsFormVisible] = useState(true);\n\n  // Billing modals\n  const [isInsufficientModalOpen, setIsInsufficientModalOpen] = useState(false);\n  const [isTopUpOpen, setIsTopUpOpen] = useState(false);'
);

content = content.replace(
  // Match the setup before useEffect up to useEffect(() => {
  /upsertHistoryEntry: workspaceHistory\.upsertHistoryEntry,\s*onAuditComplete,\s*\}\);\s*useEffect\(\(\) => \{/,
  "upsertHistoryEntry: workspaceHistory.upsertHistoryEntry,\n    onAuditComplete,\n  });\n\n  // Track 402 error specifically\n  useEffect(() => {\n    if (auditRunner.isInsufficientCredits) {\n      setIsInsufficientModalOpen(true);\n    }\n  }, [auditRunner.isInsufficientCredits]);\n\n  useEffect(() => {"
);

const endTargetRegex =
  /<CommandPalette\s*setActiveTab={setActiveTab}\s*onRunAudit={readOnly \? undefined : auditRunner\.handleSubmit}\s*onExportJson={handleExportJson}\s*\/>\s*<\/>\s*\);\s*\}/;
content = content.replace(
  endTargetRegex,
  `<CommandPalette
        setActiveTab={setActiveTab}
        onRunAudit={readOnly ? undefined : auditRunner.handleSubmit}
        onExportJson={handleExportJson}
      />

      <InsufficientCreditsModal
        open={isInsufficientModalOpen}
        onClose={() => setIsInsufficientModalOpen(false)}
        onTopUpClick={() => {
          setIsInsufficientModalOpen(false);
          setIsTopUpOpen(true);
        }}
      />

      <CreditTopUpModal
        open={isTopUpOpen}
        onClose={() => setIsTopUpOpen(false)}
        getAuthHeaders={getAuthHeaders}
      />
    </>
  );
}`
);

fs.writeFileSync(filePath, content, "utf-8");
console.log("Successfully patched " + filePath);
