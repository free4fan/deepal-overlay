package com.walter.overlay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * T-55: pins the T-52 ON/OFF lifecycle contract
 * (TranslationService.computeInitialState) without a device. The OS
 * auto-rebinds an enabled accessibility service after a reboot / process
 * kill with no user action, so ON may survive a service restart ONLY
 * after a clean stop (onDestroy ran) or after an explicit app open
 * (spec v2.10.2). Full truth table, 16/16.
 */
public class TranslationServiceTest {

    private boolean start(boolean firstConnect, boolean sessionAlive,
                          boolean enabled, boolean appOpenedServiceDown) {
        return TranslationService.computeInitialState(
            firstConnect, sessionAlive, enabled, appOpenedServiceDown);
    }

    @Test
    public void uncleanRestartResetsOnToOff() {
        // T-52 repro: ON -> OS kill/reboot -> new process connects
        assertFalse(start(true, true, true, false));
    }

    @Test
    public void explicitAppOpenBeatsReset() {
        // App launched while the service was down: opening the app IS
        // the explicit enable (spec v2.10.2)
        assertTrue(start(true, true, true, true));
    }

    @Test
    public void cleanStopPersistsOn() {
        // Clean stop (onDestroy ran, session_alive cleared) -> user
        // re-enables the service in a11y settings: ON restored
        assertTrue(start(true, false, true, false));
    }

    @Test
    public void sameProcessRebindKeepsExplicitToggle() {
        // A same-process rebind must not wipe an in-session state
        assertTrue(start(false, true, true, false));
        assertFalse(start(false, true, false, false));
        assertTrue(start(false, false, true, true));
        assertFalse(start(false, false, false, false));
    }

    @Test
    public void connectNeverFlipsOffToOn() {
        // No self-activation: persisted OFF stays OFF in every corner
        for (boolean fc : new boolean[]{true, false})
            for (boolean sa : new boolean[]{true, false})
                for (boolean aos : new boolean[]{true, false}) {
                    assertFalse("fc=" + fc + " sa=" + sa + " aos=" + aos,
                        start(fc, sa, false, aos));
                }
    }

    @Test
    public void fullTruthTable() {
        for (int bits = 0; bits < 16; bits++) {
            boolean fc = (bits & 8) != 0;
            boolean sa = (bits & 4) != 0;
            boolean en = (bits & 2) != 0;
            boolean aos = (bits & 1) != 0;
            boolean expected = en && !(fc && sa && en && !aos);
            assertEquals("fc=" + fc + " sa=" + sa + " en=" + en + " aos=" + aos,
                expected, start(fc, sa, en, aos));
        }
    }
}
