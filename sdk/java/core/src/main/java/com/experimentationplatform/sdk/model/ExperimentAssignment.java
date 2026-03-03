package com.experimentationplatform.sdk.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Objects;

/**
 * Represents an experiment assignment response from the platform.
 *
 * <p>Returned by {@code POST /api/v1/assignments} and by
 * {@link com.experimentationplatform.sdk.ExperimentationClient#getExperimentAssignment}.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public class ExperimentAssignment {

    @JsonProperty("experiment_id")
    private String experimentId;

    @JsonProperty("experiment_key")
    private String experimentKey;

    @JsonProperty("user_id")
    private String userId;

    @JsonProperty("variant_key")
    private String variantKey;

    @JsonProperty("in_experiment")
    private boolean inExperiment;

    @JsonProperty("assignment_reason")
    private String assignmentReason;

    /** No-arg constructor required for Jackson deserialization. */
    public ExperimentAssignment() {}

    /**
     * Full constructor for tests and manual construction.
     *
     * @param experimentId     unique identifier of the experiment
     * @param experimentKey    key of the experiment (human-readable)
     * @param userId           identifier of the user who was assigned
     * @param variantKey       the variant key assigned (e.g., "control", "treatment")
     * @param inExperiment     true if the user is included in this experiment
     * @param assignmentReason explanation of why the user was assigned this variant
     */
    public ExperimentAssignment(String experimentId, String experimentKey, String userId,
                                 String variantKey, boolean inExperiment, String assignmentReason) {
        this.experimentId = experimentId;
        this.experimentKey = experimentKey;
        this.userId = userId;
        this.variantKey = variantKey;
        this.inExperiment = inExperiment;
        this.assignmentReason = assignmentReason;
    }

    public String getExperimentId() { return experimentId; }
    public void setExperimentId(String experimentId) { this.experimentId = experimentId; }

    public String getExperimentKey() { return experimentKey; }
    public void setExperimentKey(String experimentKey) { this.experimentKey = experimentKey; }

    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }

    public String getVariantKey() { return variantKey; }
    public void setVariantKey(String variantKey) { this.variantKey = variantKey; }

    public boolean isInExperiment() { return inExperiment; }
    public void setInExperiment(boolean inExperiment) { this.inExperiment = inExperiment; }

    public String getAssignmentReason() { return assignmentReason; }
    public void setAssignmentReason(String assignmentReason) { this.assignmentReason = assignmentReason; }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        ExperimentAssignment that = (ExperimentAssignment) o;
        return inExperiment == that.inExperiment &&
               Objects.equals(experimentId, that.experimentId) &&
               Objects.equals(experimentKey, that.experimentKey) &&
               Objects.equals(userId, that.userId) &&
               Objects.equals(variantKey, that.variantKey) &&
               Objects.equals(assignmentReason, that.assignmentReason);
    }

    @Override
    public int hashCode() {
        return Objects.hash(experimentId, experimentKey, userId, variantKey, inExperiment, assignmentReason);
    }

    @Override
    public String toString() {
        return "ExperimentAssignment{" +
               "experimentId='" + experimentId + '\'' +
               ", experimentKey='" + experimentKey + '\'' +
               ", userId='" + userId + '\'' +
               ", variantKey='" + variantKey + '\'' +
               ", inExperiment=" + inExperiment +
               ", assignmentReason='" + assignmentReason + '\'' +
               '}';
    }
}
