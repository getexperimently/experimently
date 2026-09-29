import React from 'react';
import { allocationTotalOf, ExperimentFormAction, VariantFormData } from './formState';
import { smallInputClass } from './fieldStyles';

interface VariantsEditorProps {
  variants: VariantFormData[];
  dispatch: React.Dispatch<ExperimentFormAction>;
}

/** The variants heading, running allocation total and one row per variant. The caller supplies the section. */
export function VariantsEditor({ variants, dispatch }: VariantsEditorProps) {
  const allocationTotal = allocationTotalOf(variants);

  return (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-800">Variants</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Allocations must add up to 100%.{' '}
            <span
              className={allocationTotal === 100 ? 'text-green-700' : 'text-red-600'}
              data-testid="allocation-total"
            >
              Currently {allocationTotal}%
            </span>
          </p>
        </div>
        <button
          type="button"
          onClick={() => dispatch({ type: 'addVariant' })}
          className="text-sm text-blue-600 hover:text-blue-800 font-medium"
          data-testid="add-variant"
        >
          + Add Variant
        </button>
      </div>

      <div className="space-y-3">
        {variants.map((variant, index) => (
          <div
            key={index}
            className="flex gap-3 items-start p-3 rounded-lg border border-slate-200 bg-slate-50"
            data-testid={`variant-row-${index}`}
          >
            <div className="flex-1 space-y-2">
              <div className="flex gap-2">
                <input
                  type="text"
                  name={`variant_name_${index}`}
                  value={variant.name}
                  onChange={(e) =>
                    dispatch({ type: 'changeVariant', index, field: 'name', value: e.target.value })
                  }
                  placeholder="Variant name"
                  aria-label={`Variant ${index + 1} name`}
                  className={`flex-1 ${smallInputClass}`}
                  data-testid={`variant-name-${index}`}
                />
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    name={`variant_allocation_${index}`}
                    min={0}
                    max={100}
                    value={variant.traffic_allocation}
                    onChange={(e) =>
                      dispatch({
                        type: 'changeVariant',
                        index,
                        field: 'traffic_allocation',
                        value: Number(e.target.value),
                      })
                    }
                    aria-label={`Variant ${index + 1} allocation`}
                    className={`w-16 text-center ${smallInputClass}`}
                    data-testid={`variant-allocation-${index}`}
                  />
                  <span className="text-xs text-slate-500">%</span>
                </div>
              </div>
              <label className="inline-flex items-center gap-1.5 text-xs text-slate-600">
                <input
                  type="radio"
                  name="control_variant"
                  checked={variant.is_control}
                  onChange={() => dispatch({ type: 'setControl', index })}
                  data-testid={`variant-control-${index}`}
                />
                Control
              </label>
            </div>
            {variants.length > 1 && (
              <button
                type="button"
                onClick={() => dispatch({ type: 'removeVariant', index })}
                className="text-red-400 hover:text-red-600 text-sm mt-1"
                data-testid={`remove-variant-${index}`}
                aria-label="Remove variant"
              >
                &times;
              </button>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
