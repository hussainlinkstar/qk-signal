import { asset } from "@/lib/basePath";
import React from "react";
import Image from "next/image";

import { cx } from "@/components/ui/utils";

interface AppLogoProps {
  className?: string;
  iconClassName?: string;
  priority?: boolean;
}

/**
 * SIGV2-1087: the only render left is the Qiko mark on its own
 * (`qiko-logo.png`), which the approved in-app lockup uses where a bare mark
 * is wanted. Every "Qiko Signal" surface now renders `SignalBrandLockup`
 * instead, so the wordmark variants, the dual light/dark branch and the
 * 1.38MB SVG-wrapped raster are all gone. There is no separate dark artwork:
 * the mark is a gradient on transparency and reads on light and dark alike.
 *
 * The mark stays `unoptimized` so it renders byte-for-byte as
 * `SignalBrandLockup` does and no recorded in-app baseline moves.
 */
const QIKO_SRC = "/qiko-logo.png";
const QIKO_WIDTH = 237;
const QIKO_HEIGHT = 95;

const AppLogo = ({
  className = "",
  iconClassName = "h-10 w-auto",
  priority = false,
}: AppLogoProps) => {
  return (
    <div className={cx("flex items-center", className)}>
      <Image
        alt="Qiko"
        className={iconClassName}
        height={QIKO_HEIGHT}
        priority={priority}
        src={asset(QIKO_SRC)}
        unoptimized
        width={QIKO_WIDTH}
      />
    </div>
  );
};

export default AppLogo;
