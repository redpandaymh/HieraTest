package com.example;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import org.mockito.*;
import org.junit.jupiter.api.*;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;

public class Main_main_0_0_Test {

    @Test
    public void testMain() {
        // Redirect System.out to capture the output
        ByteArrayOutputStream outContent = new ByteArrayOutputStream();
        System.setOut(new PrintStream(outContent));
        // Call the main method using reflection
        try {
            Main.class.getMethod("main", String[].class).invoke(null, (Object) new String[] {});
        } catch (Exception e) {
            e.printStackTrace();
        }
        // Check if the output is correct
        assertEquals("Hello world!\n", outContent.toString());
        // Reset System.out
        System.setOut(System.out);
    }
}
