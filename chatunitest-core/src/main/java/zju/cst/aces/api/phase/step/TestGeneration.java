package zju.cst.aces.api.phase.step;

import lombok.Data;
import zju.cst.aces.api.config.Config;
import zju.cst.aces.api.impl.ChatGenerator;
import zju.cst.aces.api.impl.PromptConstructorImpl;
import zju.cst.aces.api.impl.RepairImpl;
import zju.cst.aces.api.impl.obfuscator.Obfuscator;
import zju.cst.aces.dto.*;
import zju.cst.aces.prompt.PromptGenerator;
import zju.cst.aces.runner.MethodRunner;
import zju.cst.aces.util.CodeExtractor;

import java.util.List;

public class TestGeneration {
    protected final Config config;
    protected PromptGenerator promptGenerator;
    protected MethodInfo methodInfo;

    public TestGeneration(Config config) {
        this.config = config;
    }

    public void setUp(PromptInfo promptInfo) {
        this.promptGenerator = new PromptGenerator(config);
        this.methodInfo = promptInfo.getMethodInfo();
    }

    public void execute(PromptConstructorImpl pc) {

        PromptInfo promptInfo = pc.getPromptInfo();
        if (promptGenerator == null) {
            setUp(promptInfo);
        }

        assert (promptInfo.getRound() != null);

        int rounds = promptInfo.getRound();
        promptInfo.addRecord(new RoundRecord(rounds));
        RoundRecord record = promptInfo.getRecords().get(rounds);
        record.setAttempt(promptInfo.getTestNum());

        if (rounds == 0) {
            config.getLogger().info("Generating test for method < " + methodInfo.methodName + " > round " + rounds + " ...");
        } else {
            config.getLogger().info("Fixing test for method < " + methodInfo.methodName + " > round " + rounds + " ...");
        }

        List<ChatMessage> prompt;
        String code;
        if (config.isEnableObfuscate()) {
            Obfuscator obfuscator = new Obfuscator(config);
            PromptInfo obfuscatedPromptInfo = new PromptInfo(promptInfo);
            obfuscator.obfuscatePromptInfo(obfuscatedPromptInfo);
            prompt = promptGenerator.generateMessages(obfuscatedPromptInfo,config.getPhaseType());
            code = generateTest(prompt, record, promptInfo);
            if (!record.isHasCode()) {
                promptInfo.setUnitTest("");
                return;
            }
            code = obfuscator.deobfuscateJava(code);
        } else {
            prompt = promptGenerator.generateMessages(promptInfo,config.getPhaseType());
            code = generateTest(prompt, record, promptInfo);
            if (!record.isHasCode()) {
                promptInfo.setUnitTest("");
                return;
            }
        }
        RepairImpl repair = new RepairImpl(config, pc);
        if (CodeExtractor.isTestMethod(code)) {
            TestSkeleton skeleton = new TestSkeleton(promptInfo); // test skeleton to wrap a test method
            code = skeleton.build(code);
        } else {
            code = repair.ruleBasedRepair(code);
        }
        promptInfo.setUnitTest(code);
        record.setCode(code);
    }

    public String generateTest(List<ChatMessage> prompt, RoundRecord record, PromptInfo promptInfo) {

        if (MethodRunner.isExceedMaxTokens(config.getMaxPromptTokens(), prompt)) {
            config.getLogger().error("Exceed max prompt tokens: " + methodInfo.methodName + " Skipped.");
            record.setPromptToken(-1);
            record.setHasCode(false);
            return "";
        }
        config.getLogger().debug("[Prompt]:\n" + prompt);

        zju.cst.aces.api.config.Model targetModel = config.getModel();
        String[] targetApiKeys = config.getApiKeys();

        if (config.isEnableDualModelJudger()) {
            boolean isFirstRound = (promptInfo.getRound() != null && promptInfo.getRound() == 0);
            boolean contextNotTooComplex = true;
            if (methodInfo != null && methodInfo.sourceCode != null) {
                // Heuristic for judger: if method lines > 50, consider it complex and use large model. Otherwise small model.
                if (methodInfo.sourceCode.split("\n").length > 50) {
                    contextNotTooComplex = false;
                }
            }

            if (isFirstRound && contextNotTooComplex) {
                if (config.getSmallModel() != null && config.getSmallModelApiKeys() != null) {
                    targetModel = config.getSmallModel();
                    targetApiKeys = config.getSmallModelApiKeys();
                    config.getLogger().info("Judger: Using small model for round 0 test generation.");
                }
            } else {
                if (config.getLargeModel() != null && config.getLargeModelApiKeys() != null) {
                    targetModel = config.getLargeModel();
                    targetApiKeys = config.getLargeModelApiKeys();
                    if (!isFirstRound) {
                        config.getLogger().info("Judger: Round > 0 (Repair/Feedback). Switching to large model.");
                    } else {
                        config.getLogger().info("Judger: Context too complex. Using large model for round 0 test generation.");
                    }
                }
            }
        }

        ChatResponse response = ChatGenerator.chat(config, prompt, targetModel, targetApiKeys);
        String content = ChatGenerator.getContentByResponse(response);
        config.getLogger().debug("[Response]:\n" + content);
        String code = ChatGenerator.extractCodeByContent(content);

        record.setPromptToken(response.getUsage().getPromptTokens());
        record.setResponseToken(response.getUsage().getCompletionTokens());
        record.setPrompt(prompt);
        record.setResponse(content);
        if (code.isEmpty()) {
            config.getLogger().info("Test for method < " + methodInfo.methodName + " > extract code failed");
            record.setHasCode(false);
            return "";
        }
        record.setHasCode(true);
        return code;
    }

}
