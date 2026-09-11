package com.experimentationplatform.sdk.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;
import java.util.Objects;

/**
 * The server's evaluation of one feature flag for one user, as returned by
 * {@code GET /api/v1/feature-flags/evaluate/{flagKey}?user_id=...} and by
 * {@link com.experimentationplatform.sdk.ExperimentationClient#evaluateFeatureFlag}.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public class FlagEvaluation {

    @JsonProperty("key")
    private String key;

    @JsonProperty("enabled")
    private boolean enabled;

    @JsonProperty("config")
    private Object config;

    /** No-arg constructor required for Jackson deserialization. */
    public FlagEvaluation() {}

    /**
     * Full constructor for tests and manual construction.
     *
     * @param key     the evaluated flag key
     * @param enabled the server's decision for this user
     * @param config  the flag's config payload (any JSON value), or {@code null}
     */
    public FlagEvaluation(String key, boolean enabled, Object config) {
        this.key = key;
        this.enabled = enabled;
        this.config = config;
    }

    /** Returns the evaluated flag key. */
    public String getKey() { return key; }
    public void setKey(String key) { this.key = key; }

    /** Returns whether the flag is on for this user. */
    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }

    /**
     * Returns the flag's config payload as returned by the server: a
     * {@code Map} for JSON objects, a {@code List} for arrays, a {@code String},
     * {@code Number} or {@code Boolean} for scalars, or {@code null}.
     */
    public Object getConfig() { return config; }
    public void setConfig(Object config) { this.config = config; }

    /**
     * Returns the config as a map when the server returned a JSON object,
     * {@code null} otherwise.
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> getConfigMap() {
        return (config instanceof Map) ? (Map<String, Object>) config : null;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        FlagEvaluation that = (FlagEvaluation) o;
        return enabled == that.enabled &&
               Objects.equals(key, that.key) &&
               Objects.equals(config, that.config);
    }

    @Override
    public int hashCode() {
        return Objects.hash(key, enabled, config);
    }

    @Override
    public String toString() {
        return "FlagEvaluation{key='" + key + "', enabled=" + enabled + ", config=" + config + "}";
    }
}
