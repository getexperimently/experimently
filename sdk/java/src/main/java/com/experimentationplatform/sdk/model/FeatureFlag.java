package com.experimentationplatform.sdk.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Objects;

/**
 * Represents a feature flag configuration returned from the API.
 *
 * <p>This is a Jackson-compatible POJO for deserializing the
 * {@code GET /api/v1/feature-flags/{key}/evaluate} response.
 *
 * <p>For multi-variant flags, the {@link #variants} list defines the possible
 * outcomes with weights that sum to 1.0 (e.g., 0.5 control / 0.5 treatment).
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public class FeatureFlag {

    private String id;
    private String key;
    private boolean enabled;

    @JsonProperty("rollout_percentage")
    private double rolloutPercentage;

    private List<Variant> variants;

    /** No-arg constructor required for Jackson deserialization. */
    public FeatureFlag() {}

    /**
     * Convenience constructor for tests and manual construction.
     *
     * @param id                unique flag identifier
     * @param key               flag key used in API calls
     * @param enabled           whether the flag is active
     * @param rolloutPercentage percentage of users to include (0.0 to 100.0)
     * @param variants          list of variants (may be null for boolean flags)
     */
    public FeatureFlag(String id, String key, boolean enabled,
                       double rolloutPercentage, List<Variant> variants) {
        this.id = id;
        this.key = key;
        this.enabled = enabled;
        this.rolloutPercentage = rolloutPercentage;
        this.variants = variants;
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getKey() { return key; }
    public void setKey(String key) { this.key = key; }

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }

    public double getRolloutPercentage() { return rolloutPercentage; }
    public void setRolloutPercentage(double rolloutPercentage) {
        this.rolloutPercentage = rolloutPercentage;
    }

    public List<Variant> getVariants() { return variants; }
    public void setVariants(List<Variant> variants) { this.variants = variants; }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        FeatureFlag that = (FeatureFlag) o;
        return enabled == that.enabled &&
               Double.compare(that.rolloutPercentage, rolloutPercentage) == 0 &&
               Objects.equals(id, that.id) &&
               Objects.equals(key, that.key) &&
               Objects.equals(variants, that.variants);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, key, enabled, rolloutPercentage, variants);
    }

    @Override
    public String toString() {
        return "FeatureFlag{id='" + id + "', key='" + key + "', enabled=" + enabled +
               ", rolloutPercentage=" + rolloutPercentage + ", variants=" + variants + "}";
    }

    /**
     * Represents a single variant within a multi-variant feature flag.
     *
     * <p>Weights across all variants in a flag should sum to approximately 1.0.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Variant {
        private String name;
        private double weight;

        /** No-arg constructor required for Jackson deserialization. */
        public Variant() {}

        /**
         * @param name   variant name (e.g., "control", "treatment", "on")
         * @param weight proportion of in-rollout users assigned this variant (0.0 to 1.0)
         */
        public Variant(String name, double weight) {
            this.name = name;
            this.weight = weight;
        }

        public String getName() { return name; }
        public void setName(String name) { this.name = name; }

        public double getWeight() { return weight; }
        public void setWeight(double weight) { this.weight = weight; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (o == null || getClass() != o.getClass()) return false;
            Variant variant = (Variant) o;
            return Double.compare(variant.weight, weight) == 0 &&
                   Objects.equals(name, variant.name);
        }

        @Override
        public int hashCode() {
            return Objects.hash(name, weight);
        }

        @Override
        public String toString() {
            return "Variant{name='" + name + "', weight=" + weight + "}";
        }
    }
}
