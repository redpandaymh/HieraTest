package com.example;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import org.mockito.*;
import org.junit.jupiter.api.*;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;

class Main_main_0_0_Test {

    @Test
    void testMain() {
        ByteArrayOutputStream outContent = new ByteArrayOutputStream();
        PrintStream originalOut = System.out;
        try {
            System.setOut(new PrintStream(outContent));
            Main.main(new String[] {});
            assertEquals("Hello world!" + System.lineSeparator(), outContent.toString());
        } finally {
            System.setOut(originalOut);
        }
    }
}
