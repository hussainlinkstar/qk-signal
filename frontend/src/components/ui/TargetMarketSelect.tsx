import React from "react";
import SelectField, { type SelectFieldProps } from "./SelectField";
import { TARGET_MARKET_OPTIONS } from "@/lib/targetMarket";

export default function TargetMarketSelect(props: SelectFieldProps) {
  return (
    <SelectField {...props}>
      {TARGET_MARKET_OPTIONS.map((country) => (
        <option key={country.code} value={country.code}>
          {country.name}
        </option>
      ))}
    </SelectField>
  );
}
