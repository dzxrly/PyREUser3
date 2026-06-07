module.exports = async ({github, context, core}) => {
    try {
        const issue = context.payload.issue;
        const body = issue.body || "";
        const title = (issue.title || "").toLowerCase();

        console.log(`Checking issue #${issue.number}: ${title}`);

        const bugTemplatePattern = /Affected Area\s*\/\s*影响范围/i;
        const isBugReportTemplate = bugTemplatePattern.test(body);
        console.log("Is Bug Report template?", isBugReportTemplate);

        const bugKeywords = [
            "bug", "crash", "error", "exception", "traceback", "not working",
            "failed", "failure", "wrong output", "cannot install",
            "崩溃", "报错", "错误", "异常", "无法运行", "无法安装", "失败", "输出错误"
        ];

        if (isBugReportTemplate) {
            console.log("Valid Bug Report template detected.");
            return;
        }

        const lowerBody = body.toLowerCase();
        const hasBugKeywords = bugKeywords.some(keyword =>
            title.includes(keyword) || lowerBody.includes(keyword)
        );

        if (!hasBugKeywords) {
            console.log("No bug keywords detected. Ignoring.");
            return;
        }

        console.log("Detected bug keywords in a non-bug issue. Sending template reminder.");

        await github.rest.issues.createComment({
            owner: context.repo.owner,
            repo: context.repo.repo,
            issue_number: issue.number,
            body:
                "**Format reminder / 格式提醒**\n\n" +
                "This issue looks like a bug report, but it was not opened with the **Bug Report / 问题报告** template.\n\n" +
                "If you are reporting a reproducible PyREUser3 bug, please close this issue and open a new one with the bug template so you can provide the PyREUser3 version, Python version, OS, command/code, schema context, and traceback.\n\n" +
                "这个 Issue 看起来像 Bug 反馈，但没有使用 **Bug Report / 问题报告** 模板。\n\n" +
                "如果你要反馈可复现的 PyREUser3 问题，请关闭此 Issue，并使用 Bug 模板重新提交，以便补充 PyREUser3 版本、Python 版本、操作系统、命令/代码、模板上下文和异常堆栈。"
        });
    } catch (error) {
        console.error("Script failed with error:", error);
        core.setFailed(`Action failed: ${error.message}`);
    }
};
