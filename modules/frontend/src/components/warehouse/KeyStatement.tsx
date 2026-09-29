import React from 'react';
import type { PublicKeyStatement } from '@modules/services/warehouse';
import { CopyBlock } from '@modules/components/warehouse/common';

/**
 * The statement that registers a platform-generated public key on the
 * Snowflake user. Only the public half exists outside the API; the private
 * key is never sent to the dashboard.
 */
export function KeyStatement({ statement, heading, pending }: { statement: PublicKeyStatement; heading: string; pending?: boolean }) {
  return (
    <section
      aria-labelledby="wh-key-statement-heading"
      data-testid="warehouse-key-statement"
      className="space-y-3 rounded-md border border-blue-200 bg-blue-50 p-4"
    >
      <h2 id="wh-key-statement-heading" className="text-base font-semibold text-slate-900">
        {heading}
      </h2>
      <p className="text-sm text-slate-800">
        Run this in Snowflake as a role that can alter the user (for example SECURITYADMIN), then test the connection.
        {pending && ' The current key keeps working until a test with the new key passes.'}
      </p>
      <CopyBlock label="Snowflake statement" text={statement.statement} testId="warehouse-key-statement-sql" />
      <p className="text-sm text-slate-800">
        Key fingerprint <code className="font-mono text-xs">{statement.public_key_fingerprint}</code>: compare it with the
        fingerprint <code className="font-mono text-xs">DESC USER</code> shows for the key slot the statement sets.
      </p>
    </section>
  );
}

export default KeyStatement;
