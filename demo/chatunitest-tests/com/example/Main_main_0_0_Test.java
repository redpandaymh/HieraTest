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
    void testMain() {
        ByteArrayOutputStream capturedOutput = new ByteArrayOutputStream();
        PrintStream originalOut = System.out;
        try {
            System.setOut(new PrintStream(capturedOutput));
            Main.main(new String[] {});
            String output = capturedOutput.toString().trim();
            assertTrue(output.contains("Hello world!"));
        } finally {
            System.setOut(originalOut);
        }
    }
}
