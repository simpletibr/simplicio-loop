package com.example

import kotlin.test.Test
import kotlin.test.assertEquals

class HealthControllerTest {
    @Test
    fun healthReturnsOk() {
        assertEquals(mapOf("ok" to true), HealthController().health())
    }
}
