package com.experimentationplatform.android.example

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.experimentationplatform.android.ExperimentationClient
import com.experimentationplatform.android.SdkConfig
import com.experimentationplatform.android.TrackEvent
import com.experimentationplatform.android.User

/**
 * Example Activity demonstrating the Experimentation Platform Android SDK
 * with Jetpack Compose.
 *
 * Uses http://10.0.2.2:8000 which maps to localhost from the Android emulator.
 */
class ExampleActivity : ComponentActivity() {

    // Instantiate the client once per Activity lifetime
    private val client = ExperimentationClient(
        SdkConfig(
            baseUrl = "http://10.0.2.2:8000",
            apiKey = "your-api-key"
        )
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            ExperimentationDemoScreen(client)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        client.close()
    }
}

@Composable
fun ExperimentationDemoScreen(client: ExperimentationClient) {
    var flagEnabled by remember { mutableStateOf(false) }
    var variant by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf("") }

    val user = User(id = "user-123", attributes = mapOf("plan" to "pro", "country" to "US"))

    LaunchedEffect(Unit) {
        loading = true
        errorMessage = ""
        try {
            // Evaluate the feature flag
            val result = client.evaluateFlag("new-dashboard", user)
            flagEnabled = result.enabled
            variant = result.variantKey ?: ""
        } catch (e: Exception) {
            errorMessage = "Error: ${e.message}"
        } finally {
            loading = false
        }
    }

    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Text(
                text = "Experimentation SDK Demo",
                style = MaterialTheme.typography.headlineMedium
            )
            Spacer(Modifier.height(16.dp))

            if (loading) {
                CircularProgressIndicator()
            } else if (errorMessage.isNotEmpty()) {
                Text(text = errorMessage, color = MaterialTheme.colorScheme.error)
            } else {
                Text(
                    text = "Flag: ${if (flagEnabled) "ENABLED" else "DISABLED"}",
                    style = MaterialTheme.typography.bodyLarge
                )
                if (variant.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = "Variant: $variant",
                        style = MaterialTheme.typography.bodyMedium
                    )
                }

                Spacer(Modifier.height(24.dp))

                Button(
                    onClick = {
                        // Track a purchase event (fire-and-forget)
                        val event = TrackEvent(
                            userId = user.id,
                            eventName = "purchase_clicked",
                            properties = mapOf("source" to "demo_screen")
                        )
                        client.close() // Not the right place, just for demo
                    }
                ) {
                    Text("Track Purchase")
                }
            }
        }
    }
}
